cmake_minimum_required(VERSION 3.28.0...3.28.0 FATAL_ERROR)

foreach(var Slicer_SOURCE_DIR TEST_BINARY_DIR TEST_C_COMPILER)
  if(NOT DEFINED ${var})
    message(FATAL_ERROR "${var} is required")
  endif()
endforeach()
unset(ENV{LD_LIBRARY_PATH})
unset(ENV{LD_PRELOAD})

# Use native libraries so missing versioned links or private Qt dependencies
# fail when loading the installed executable, not just when comparing a list.
function(check_qt_install major minor)
  set(root "${TEST_BINARY_DIR}/qt${major}-${minor}")
  set(sdk "${root}/sdk")
  set(stage "${root}/install")
  file(REMOVE_RECURSE "${root}")
  file(MAKE_DIRECTORY "${sdk}/lib" "${sdk}/libexec" "${sdk}/resources"
    "${sdk}/translations/qtwebengine_locales" "${root}/source")
  set(modules Core Gui DBus X11Extras Qml QmlModels Positioning)
  set(dependencies_QmlModels Qml)
  set(dependencies_Quick QmlModels)
  set(dependencies_Multimedia Core)
  if(major EQUAL 6)
    list(APPEND modules Concurrent QmlWorkerScript)
    set(dependencies_Multimedia Concurrent)
    if(minor GREATER_EQUAL 11)
      list(APPEND modules QmlMeta)
      set(dependencies_QmlMeta QmlModels QmlWorkerScript)
      set(dependencies_Quick QmlMeta)
    endif()
  endif()
  list(APPEND modules Quick QuickWidgets WebEngineCore Multimedia)
  set(dependencies_WebEngineCore Quick Positioning)
  if(major EQUAL 5)
    list(APPEND modules WebEngine)
    set(dependencies_WebEngine WebEngineCore)
  endif()
  set(imported_targets "")
  foreach(module IN LISTS modules)
    set(code "")
    set(expression "0")
    set(link_options "")
    foreach(dependency IN LISTS dependencies_${module})
      string(APPEND code "int fixture_${dependency}(void);\n")
      string(APPEND expression " + fixture_${dependency}()")
      list(APPEND link_options "-lQt${major}${dependency}")
    endforeach()
    string(APPEND code "int fixture_${module}(void) { return ${expression}; }\n")
    file(WRITE "${root}/${module}.c" "${code}")
    set(name "libQt${major}${module}.so")
    execute_process(COMMAND "${TEST_C_COMPILER}" -shared -fPIC "-Wl,--no-as-needed"
      "${root}/${module}.c" "-L${sdk}/lib" ${link_options}
      "-Wl,-soname,${name}.${major}" "-Wl,-rpath,$ORIGIN"
      -o "${sdk}/lib/${name}.${major}.${minor}.0"
      COMMAND_ERROR_IS_FATAL ANY)
    file(CREATE_LINK "${name}.${major}.${minor}.0" "${sdk}/lib/${name}.${major}" SYMBOLIC)
    file(CREATE_LINK "${name}.${major}" "${sdk}/lib/${name}" SYMBOLIC)
    string(APPEND imported_targets
      "add_library(Qt${major}::${module} SHARED IMPORTED)\n"
      "set_target_properties(Qt${major}::${module} PROPERTIES\n"
      "  IMPORTED_LOCATION_RELEASE \"${sdk}/lib/${name}.${major}.${minor}.0\")\n")
  endforeach()
  file(WRITE "${root}/main.c"
    "int fixture_WebEngineCore(void); int fixture_Multimedia(void);\n"
    "int main(void) { return fixture_WebEngineCore() + fixture_Multimedia(); }\n")
  execute_process(COMMAND "${TEST_C_COMPILER}" "-Wl,--no-as-needed" "${root}/main.c" "-L${sdk}/lib"
    "-lQt${major}WebEngineCore" "-lQt${major}Multimedia" "-Wl,-rpath-link,${sdk}/lib"
    -o "${sdk}/libexec/QtWebEngineProcess" COMMAND_ERROR_IS_FATAL ANY)
  file(WRITE "${sdk}/translations/qtwebengine_locales/en-US.pak" "fixture locale\n")
  file(WRITE "${root}/source/FindQt${major}.cmake" "set(Qt${major}_FOUND TRUE)\n")
  if(major EQUAL 6)
    # An unrelated Qt 5 target must not determine Qt 6 library filenames.
    string(APPEND imported_targets "add_library(Qt5::Core INTERFACE IMPORTED)\n")
    set(webengine WebEngineCore)
  else()
    set(webengine WebEngine)
  endif()
  file(WRITE "${root}/source/CMakeLists.txt" "
cmake_minimum_required(VERSION 3.28)
project(QtLibraryInstall NONE)
list(PREPEND CMAKE_MODULE_PATH \"${root}/source\")
set(CMAKE_BUILD_TYPE Debug)
set(CTK_QT_VERSION ${major})
set(Qt${major}_VERSION_MAJOR ${major})
set(Qt${major}_VERSION_MINOR ${minor})
set(Qt${major}_VERSION_PATCH 0)
set(Qt5_VERSION_MAJOR 5)
set(Qt5_VERSION_MINOR 15)
set(Qt5_VERSION_PATCH 0)
set(Slicer_INSTALL_ROOT .)
set(Slicer_INSTALL_LIB_DIR lib/application)
set(Slicer_INSTALL_QtPlugins_DIR lib/QtPlugins)
set(Slicer_BUILD_QT_DESIGNER_PLUGINS OFF)
${imported_targets}
set(QT_LIBRARIES Qt${major}::Core Qt${major}::Quick Qt${major}::QuickWidgets
  Qt${major}::${webengine} Qt${major}::Multimedia)
include(\"${Slicer_SOURCE_DIR}/CMake/SlicerFunctionInstallLibrary.cmake\")
include(\"${Slicer_SOURCE_DIR}/CMake/SlicerBlockInstallQt.cmake\")
")
  execute_process(COMMAND "${CMAKE_COMMAND}" -S "${root}/source" -B "${root}/build"
    COMMAND_ERROR_IS_FATAL ANY)
  execute_process(COMMAND "${CMAKE_COMMAND}" --install "${root}/build" --prefix "${stage}"
    --component Runtime COMMAND_ERROR_IS_FATAL ANY)
  foreach(resource libexec/QtWebEngineProcess libexec/qt.conf
      share/QtTranslations/qtwebengine_locales/en-US.pak)
    if(NOT EXISTS "${stage}/${resource}")
      message(FATAL_ERROR "Qt ${major}.${minor} package is missing ${resource}")
    endif()
  endforeach()
  file(RENAME "${sdk}" "${root}/unavailable-sdk")
  execute_process(COMMAND "${CMAKE_COMMAND}" -E env --unset=LD_PRELOAD
    "LD_LIBRARY_PATH=${stage}/lib/application" "${stage}/libexec/QtWebEngineProcess"
    RESULT_VARIABLE result ERROR_VARIABLE error)
  if(NOT result EQUAL 0)
    message(FATAL_ERROR "Qt ${major}.${minor} package cannot load without its SDK: ${error}")
  endif()
endfunction()

function(check_windows_deploy_arguments major)
  set(root "${TEST_BINARY_DIR}/windows-qt${major}")
  file(REMOVE_RECURSE "${root}")
  file(MAKE_DIRECTORY "${root}/sdk/bin" "${root}/source")
  file(WRITE "${root}/sdk/bin/windeployqt.exe"
    "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"${root}/deploy-arguments.txt\"\n")
  file(CHMOD "${root}/sdk/bin/windeployqt.exe"
    PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE)
  file(WRITE "${root}/source/FindQt${major}.cmake" "set(Qt${major}_FOUND TRUE)\n")
  set(imported_targets "")
  foreach(module Core Gui Qml Quick QuickWidgets WebEngine WebEngineCore Positioning
      QmlModels QmlMeta QmlWorkerScript Concurrent)
    string(APPEND imported_targets
      "add_library(Qt${major}::${module} SHARED IMPORTED)\n"
      "set_target_properties(Qt${major}::${module} PROPERTIES\n"
      "  IMPORTED_LOCATION_RELEASE \"${root}/sdk/bin/Qt${major}${module}.dll\")\n")
  endforeach()
  set(webengine WebEngine)
  if(major EQUAL 6)
    set(webengine WebEngineCore)
  endif()
  file(WRITE "${root}/source/CMakeLists.txt" "
cmake_minimum_required(VERSION 3.28)
project(QtDeployArguments NONE)
set(UNIX FALSE)
set(WIN32 TRUE)
set(CTK_QT_VERSION ${major})
set(CMAKE_WINDOWS_KITS_10_DIR \"${root}/sdk\")
set(QT_BINARY_DIR \"${root}/sdk/bin\")
set(Slicer_MAIN_PROJECT_APPLICATION_NAME Slicer)
set(Slicer_BUILD_QT_DESIGNER_PLUGINS OFF)
list(PREPEND CMAKE_MODULE_PATH \"${root}/source\")
${imported_targets}
add_executable(Qt${major}::uic IMPORTED)
set_target_properties(Qt${major}::uic PROPERTIES IMPORTED_LOCATION \"${root}/sdk/bin/uic.exe\")
set(QT_LIBRARIES Qt${major}::Core Qt${major}::${webengine})
include(\"${Slicer_SOURCE_DIR}/CMake/SlicerBlockInstallQt.cmake\")
")
  execute_process(COMMAND "${CMAKE_COMMAND}" -S "${root}/source" -B "${root}/build"
    COMMAND_ERROR_IS_FATAL ANY)
  execute_process(COMMAND "${CMAKE_COMMAND}" --install "${root}/build"
    --prefix "${root}/install" --component Runtime COMMAND_ERROR_IS_FATAL ANY)
  file(STRINGS "${root}/deploy-arguments.txt" arguments)
  foreach(argument -qml -quick -quickwidgets -webenginecore -positioning)
    if(NOT argument IN_LIST arguments)
      message(FATAL_ERROR "Qt ${major} Windows deployment is missing ${argument}: ${arguments}")
    endif()
  endforeach()
  foreach(argument -qmlmodels -qmlmeta -qmlworkerscript -concurrent)
    if(argument IN_LIST arguments)
      message(FATAL_ERROR "Linux-only dependency passed to windeployqt: ${argument}")
    endif()
  endforeach()
endfunction()

check_qt_install(5 15)
check_qt_install(6 8)
check_qt_install(6 11)
check_windows_deploy_arguments(5)
check_windows_deploy_arguments(6)
message(STATUS "SUCCESS: Qt packages load independently of their SDK")
