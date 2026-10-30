import logging
import threading
import unittest
from logging.handlers import BufferingHandler
from unittest.mock import Mock

import slicer


class LoggingTest(unittest.TestCase):
    def setUp(self):
        self.handler = type(slicer.pythonApplicationLogHandler)()
        self.addCleanup(self.handler.close)
        self.logger = logging.Logger("SlicerLoggingTest", logging.DEBUG)
        self.logger.addHandler(self.handler)
        self.otherHandler = BufferingHandler(10)
        self.logger.addHandler(self.otherHandler)
        self.handler.handleError = Mock()

    def logFromWorker(self, message):
        worker = threading.Thread(target=self.logger.debug, args=(message,), daemon=True)
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive(), "Logging worker did not finish")

    def test_worker_logging_and_close(self):
        message = "Slicer logging worker before close"
        self.logFromWorker(message)
        slicer.app.processEvents()
        model = slicer.app.errorLogModel()
        self.assertTrue(any(message in model.logEntryDescription(row) for row in range(model.logEntryCount())))
        self.handler.handleError.assert_not_called()

        self.handler.close()
        # Formatting is the first operation before constructing Qt log data.
        self.handler.format = Mock(side_effect=AssertionError("Closed handler reached its Qt output path"))
        self.logFromWorker("Slicer logging worker after close")
        self.handler.format.assert_not_called()
        self.handler.handleError.assert_not_called()
        self.assertEqual([record.getMessage() for record in self.otherHandler.buffer],
                         [message, "Slicer logging worker after close"])

    def test_close_waits_for_current_emission(self):
        entered, proceed, closing, closed = (threading.Event() for _ in range(4))
        originalFormat = self.handler.format

        def formatRecord(record):
            entered.set()
            if not proceed.wait(5):
                raise RuntimeError("Test did not release the logging worker")
            return originalFormat(record)

        def closeHandler():
            closing.set()
            self.handler.close()
            closed.set()

        self.handler.format = formatRecord
        worker = threading.Thread(target=self.logger.debug, args=("Slicer in-flight log",), daemon=True)
        closer = threading.Thread(target=closeHandler, daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            closer.start()
            self.assertTrue(closing.wait(5))
            self.assertFalse(closed.wait(0.1), "Close returned while an emission was using Qt")
        finally:
            proceed.set()
            worker.join(5)
            if closer.ident is not None:
                closer.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertTrue(closed.is_set())
        self.handler.handleError.assert_not_called()
