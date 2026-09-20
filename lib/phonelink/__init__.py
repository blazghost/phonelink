"""Shared code for phonelink's windows and its D-Bus helper.

The three GTK programs -- the reply window, the toast service and the Messages
window -- used to load each other by file path to share a palette, an avatar or
a D-Bus call. They import this package instead:

    theme       the Omarchy palette and the CSS built from it
    widgets     the small GTK 4 / libadwaita pieces they all draw
    apps        opening a notification's app on the desktop
    kdeconnect  talking to kdeconnectd: devices, notifications, replies
    helper      the same, as a subprocess, so a window can be driven by a stub
    sms         phone numbers, contacts, dates and the SMS/MMS message

Each entry script puts `lib/` on sys.path and imports from here; nothing in the
package imports an entry script back.
"""
