# KDE Connect bug report (draft): share input devices never captures on Hyprland

File at <https://bugs.kde.org/enter_bug.cgi?product=kdeconnect> (component:
`common` or the plugin's own, if listed). Needs a KDE Identity login.

---

**Summary:** Share input devices: InputCapture `barrier_id` sent as `i`, portal
spec says `u`; xdg-desktop-portal-hyprland rejects the barrier

**Version:** kdeconnect 26.08.2 (Arch), xdg-desktop-portal-hyprland 1.4.1,
Hyprland 0.56.2

**What happens:** With the *Share input devices* plugin enabled for a paired
phone, moving the pointer to the configured screen edge does nothing. The
plugin does create an InputCapture session, connects to EIS and calls
`GetZones`, but `SetPointerBarriers` comes back with the barrier rejected, so
capture never activates.

**Why:** the plugin builds the barrier dictionary with `barrier_id` as a
signed int (`i`). The InputCapture portal documents it as `u`
(<https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.InputCapture.html>),
and xdg-desktop-portal-hyprland reads it as such: the id comes through as 0,
which is invalid, and is reported back as failed.

**Evidence** (`busctl --user monitor` while enabling the plugin):

```
Member=SetPointerBarriers
    STRING "barrier_id";  VARIANT "i" { INT32 1; }
    STRING "position";    (iiii) 0 0 0 911
Member=Response
    UINT32 0;
    STRING "failed_barriers";  VARIANT "au" { ARRAY "u" { UINT32 0; } }
```

The same barrier set from a minimal Gio client against the same session
setup is accepted with `barrier_id` as `GLib.Variant("u", 1)`
(`failed_barriers = []`) and rejected with `GLib.Variant("i", 1)`
(`failed_barriers = [0]`).

**Fix:** send `barrier_id` as `uint` (e.g. `QVariant::fromValue<uint>(id)`)
when building the `SetPointerBarriers` argument. xdg-desktop-portal-kde
presumably tolerates the signed type, which is why this works on Plasma.
