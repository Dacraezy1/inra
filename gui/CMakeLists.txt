cmake_minimum_required(VERSION 3.16)
project(inra-gui VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)

add_executable(inra-gui
    main.cpp
    mainwindow.h
    mainwindow.cpp
)

target_link_libraries(inra-gui PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
)
