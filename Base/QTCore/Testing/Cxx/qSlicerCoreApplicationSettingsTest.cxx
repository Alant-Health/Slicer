/*==============================================================================

  Program: 3D Slicer

  Copyright (c) Kitware Inc.

  See COPYRIGHT.txt
  or http://www.slicer.org/copyright/copyright.txt for details.

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

==============================================================================*/

#include "qSlicerCoreApplication.h"
#include "qSlicerCoreCommandOptions.h"
#include "vtkSlicerConfigure.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QSettings>
#include <QTemporaryDir>

#include <iostream>

int qSlicerCoreApplicationSettingsTest(int argc, char* argv[])
{
  QTemporaryDir temporaryDirectory;
  if (!temporaryDirectory.isValid())
  {
    std::cerr << "Cannot create isolated settings directory" << std::endl;
    return EXIT_FAILURE;
  }
  const QString home = temporaryDirectory.path();
  qputenv("SLICER_HOME", home.toUtf8());
  QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, home + "/user");
  QSettings::setPath(QSettings::IniFormat, QSettings::SystemScope, home + "/system");
  const QString applicationName = "SettingsInitializationTest";
  QCoreApplication::setApplicationName(applicationName);
  qSlicerCoreApplication::setAttribute(qSlicerCoreApplication::AA_DisablePython);

  QStringList arguments;
  for (int index = 1; index < argc; ++index)
  {
    arguments << argv[index];
  }
  const bool temporary = arguments.contains("--disable-settings") || arguments.contains("--testing");
  const bool keep = arguments.contains("--keep-temporary-settings");

#ifdef Q_OS_DARWIN
  const QString organization = Slicer_ORGANIZATION_DOMAIN;
#else
  const QString organization = Slicer_ORGANIZATION_NAME;
#endif
  QSettings ordinary(QSettings::IniFormat, QSettings::UserScope, organization, applicationName);
  ordinary.setValue("SettingsTest/Override", "ordinary");
  ordinary.setValue("SettingsTest/OrdinaryOnly", true);
  ordinary.sync();
  QSettings previousTemporary(QSettings::IniFormat, QSettings::UserScope, organization, applicationName + "-tmp");
  previousTemporary.setValue("SettingsTest/Override", "kept");
  previousTemporary.setValue("SettingsTest/TemporaryOnly", true);
  previousTemporary.sync();

  const QString defaultsPath = home + "/" Slicer_SHARE_DIR "/" + applicationName + "DefaultSettings.ini";
  QSettings defaults(defaultsPath, QSettings::IniFormat);
  defaults.setValue("SettingsTest/Override", "default");
  defaults.setValue("SettingsTest/DefaultOnly", true);
  defaults.setValue("Extensions/AutoUpdateCheck", false);
  defaults.setValue("ApplicationUpdate/AutoUpdateCheck", false);
  defaults.sync();
  if (ordinary.status() != QSettings::NoError || previousTemporary.status() != QSettings::NoError || defaults.status() != QSettings::NoError)
  {
    std::cerr << "Cannot write settings fixture" << std::endl;
    return EXIT_FAILURE;
  }
  QFile ordinaryFile(ordinary.fileName());
  if (!ordinaryFile.open(QIODevice::ReadOnly))
  {
    return EXIT_FAILURE;
  }
  const QByteArray ordinaryContents = ordinaryFile.readAll();
  ordinaryFile.close();

  qSlicerCoreApplication app(argc, argv);
  QSettings* userSettings = app.userSettings();
  QSettings* revisionSettings = app.revisionUserSettings();
  const QString expectedName = applicationName + (temporary ? "-tmp" : "");
  const QString expectedValue = temporary ? (keep ? "kept" : "default") : "ordinary";
  if (app.applicationName() != expectedName || app.coreCommandOptions()->settingsDisabled() != temporary
      || userSettings->fileName() != (temporary ? previousTemporary.fileName() : ordinary.fileName()) || !revisionSettings->fileName().startsWith(home + "/")
      || QFileInfo(revisionSettings->fileName()).fileName().startsWith(applicationName + "-tmp") != temporary)
  {
    std::cerr << "Wrong settings profile: " << qPrintable(userSettings->fileName()) << ", " << qPrintable(revisionSettings->fileName()) << std::endl;
    return EXIT_FAILURE;
  }
  if (!app.defaultSettings() || app.defaultSettings()->fileName() != defaultsPath || userSettings->value("SettingsTest/Override").toString() != expectedValue
      || !userSettings->value("SettingsTest/DefaultOnly").toBool() || userSettings->contains("SettingsTest/OrdinaryOnly") == temporary
      || userSettings->contains("SettingsTest/TemporaryOnly") != (temporary && keep) || revisionSettings->value("SettingsTest/Override").toString() != "default"
      || !revisionSettings->value("SettingsTest/DefaultOnly").toBool())
  {
    std::cerr << "Defaults, existing values, or temporary settings were not preserved as requested" << std::endl;
    return EXIT_FAILURE;
  }
  userSettings->sync();
  revisionSettings->sync();
  if (temporary)
  {
    if (!ordinaryFile.open(QIODevice::ReadOnly) || ordinaryFile.readAll() != ordinaryContents)
    {
      std::cerr << "Temporary settings mode modified the ordinary profile" << std::endl;
      return EXIT_FAILURE;
    }
  }
  return EXIT_SUCCESS;
}
