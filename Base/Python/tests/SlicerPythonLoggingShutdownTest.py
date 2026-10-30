"""Verify that a worker can log after aboutToQuit without entering Qt."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def runChild(output, mode):
    import atexit
    import logging
    import threading
    from logging.handlers import BufferingHandler
    from unittest.mock import Mock

    import qt
    import slicer

    handler = slicer.pythonApplicationLogHandler
    logger = logging.Logger("SlicerShutdownTest", logging.DEBUG)
    otherHandler = BufferingHandler(10)
    logger.addHandler(handler)
    logger.addHandler(otherHandler)
    gate, ready, done = threading.Event(), threading.Event(), threading.Event()
    beforeMessage = "Worker log before aboutToQuit"
    result = {"about_to_quit_count": 0, "ordinary_log_reached_qt": False}

    def worker():
        logger.debug(beforeMessage)
        ready.set()
        if gate.wait(10):
            logger.debug("Worker log after aboutToQuit")
            done.set()

    def aboutToQuit():
        result["about_to_quit_count"] += 1
        if result["about_to_quit_count"] != 1:
            return
        if mode == "guarded":
            # A missing shutdown guard must fail this test before accessing Qt
            # objects whose lifetime is ending. Never reset this evidence.
            handler.format = Mock(side_effect=AssertionError("Qt log output reached after aboutToQuit"))
            handler.handleError = Mock()
        gate.set()

    def requestQuit():
        if ready.wait(5):
            slicer.app.processEvents()
            model = slicer.app.errorLogModel()
            result["ordinary_log_reached_qt"] = any(
                beforeMessage in model.logEntryDescription(row) for row in range(model.logEntryCount()))
        slicer.app.quit()

    def writeResult():
        result.update(worker_completed=done.is_set(), other_handler_received=len(otherHandler.buffer) == 2)
        if mode == "guarded":
            result.update(qt_output_reached=handler.format.called, handler_error=handler.handleError.called)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream)

    # Let Python finalization wait for the worker before recording its result.
    thread = threading.Thread(target=worker)
    slicer.app.connect("aboutToQuit()", aboutToQuit)
    atexit.register(writeResult)
    thread.start()
    qt.QTimer.singleShot(0, requestQuit)


def runParent(launcher):
    with tempfile.TemporaryDirectory(prefix="SlicerLoggingShutdown-") as directory:
        for mode in ("guarded", "native"):
            output = Path(directory) / (mode + ".json")
            env = dict(os.environ, SLICER_LOGGING_TEST_OUTPUT=str(output), SLICER_LOGGING_TEST_MODE=mode)
            process = subprocess.run(
                [launcher, "--disable-settings", "--ignore-slicerrc", "--no-splash", "--no-main-window", "--disable-modules",
                 "--python-script", str(Path(__file__).resolve())],
                env=env, capture_output=True, text=True, timeout=90, check=False)
            if process.returncode:
                raise RuntimeError(f"Slicer exited with {process.returncode}\n{process.stdout}\n{process.stderr}")
            result = json.loads(output.read_text(encoding="utf-8"))
            expected = {"about_to_quit_count": 1, "ordinary_log_reached_qt": True,
                        "worker_completed": True, "other_handler_received": True}
            if mode == "guarded":
                expected.update(qt_output_reached=False, handler_error=False)
            if result != expected:
                raise AssertionError(result)
        print("Background logging after aboutToQuit passed")


if __name__ == "__main__":
    if "SLICER_LOGGING_TEST_OUTPUT" in os.environ:
        runChild(Path(os.environ["SLICER_LOGGING_TEST_OUTPUT"]), os.environ["SLICER_LOGGING_TEST_MODE"])
    else:
        runParent(sys.argv[1])
