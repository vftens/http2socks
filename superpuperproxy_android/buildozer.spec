[app]
title = SuperPuperProxy
package.name = superpuperproxy
package.domain = org.drvital

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 1.0
requirements = python3,kivy

icon.filename = %(source.dir)s/icon.png

orientation = portrait
fullscreen = 0

# Needed to open sockets / act as a local proxy server
android.permissions = INTERNET,ACCESS_NETWORK_STATE,FOREGROUND_SERVICE

android.api = 33
android.minapi = 21
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 1
