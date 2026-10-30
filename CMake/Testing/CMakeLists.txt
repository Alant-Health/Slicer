
#
# Helper macro
#
macro(add_cmakescript_test testname script)
  add_test(cmake_${testname} ${CMAKE_COMMAND}
    -DTEST_${testname}:BOOL=ON
    -P ${CMAKE_SOURCE_DIR}/${script})
  set_tests_properties(cmake_${testname} PROPERTIES
    LABELS CMake
    PASS_REGULAR_EXPRESSION "SUCCESS")
endmacro()

#
# Add 'CMake script' Tests
#
add_cmakescript_test(
  list_to_string_test
  CMake/ListToString.cmake)

add_cmakescript_test(
  slicer_setting_variable_message_test
  CMake/UseSlicerMacros.cmake)

add_cmakescript_test(
  slicer_block_ctk_app_launcher_settings_test
  CMake/Testing/SlicerBlockCTKAppLauncherSettingsTest.cmake)

add_test(
  NAME cmake_slicer_python_requirements_test
  COMMAND ${CMAKE_COMMAND}
    "-DSlicer_SOURCE_DIR=${Slicer_SOURCE_DIR}"
    "-DTEST_BINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/SlicerPythonRequirementsTest"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/SlicerPythonRequirementsTest.cmake"
  )
set_tests_properties(cmake_slicer_python_requirements_test PROPERTIES
  LABELS CMake
  PASS_REGULAR_EXPRESSION "SUCCESS"
  )

if(UNIX AND Slicer_USE_PYTHONQT)
  add_test(
    NAME slicer_macos_packaging_test
    COMMAND "${PYTHON_EXECUTABLE}" "${Slicer_SOURCE_DIR}/Utilities/Scripts/test_slicer_macos_packaging.py"
    )
  set_tests_properties(slicer_macos_packaging_test PROPERTIES LABELS CMake TIMEOUT 180)
endif()

if(UNIX)
  add_test(
    NAME cmake_slicer_extension_cpack_bundle_fixup_path_test
    COMMAND ${CMAKE_COMMAND}
      "-DSlicer_SOURCE_DIR=${Slicer_SOURCE_DIR}"
      "-DTEST_BINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/SlicerExtensionCPackBundleFixupPathTest"
      -P "${CMAKE_CURRENT_SOURCE_DIR}/SlicerExtensionCPackBundleFixupPathTest.cmake"
    )
  set_tests_properties(cmake_slicer_extension_cpack_bundle_fixup_path_test PROPERTIES
    LABELS CMake
    PASS_REGULAR_EXPRESSION "SUCCESS"
    )
endif()

if(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND NOT CMAKE_CROSSCOMPILING)
  add_test(
    NAME cmake_slicer_qt_library_install_test
    COMMAND ${CMAKE_COMMAND}
      "-DSlicer_SOURCE_DIR=${Slicer_SOURCE_DIR}"
      "-DTEST_BINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}/SlicerQtLibraryInstallTest"
      "-DTEST_C_COMPILER=${CMAKE_C_COMPILER}"
      -P "${CMAKE_CURRENT_SOURCE_DIR}/SlicerQtLibraryInstallTest.cmake"
    )
  set_tests_properties(cmake_slicer_qt_library_install_test PROPERTIES
    LABELS CMake
    PASS_REGULAR_EXPRESSION "SUCCESS"
    )
endif()
