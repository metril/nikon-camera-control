/** Recognising "the camera is plugged in but the app may not open it" from a failed Connect. */

/** Error codes the backend may use for a USB permission failure. */
const CODES = new Set([
  'CAMERA_PERMISSION_DENIED',
  'CAMERA_NO_PERMISSION',
  'CAMERA_ACCESS_DENIED',
  'USB_PERMISSION_DENIED',
  'USB_PERMISSION',
  'PERMISSION_DENIED',
])
// Until the backend gives a distinct code, match what libgphoto2 and the OS say.
const MESSAGE = /permission|not permitted|access denied|udev|operation not permitted/i

export function isNoPermission(e) {
  if (!e) return false
  if (e.code && CODES.has(String(e.code))) return true
  return MESSAGE.test(String(e.message || ''))
}

/** What to run on the host to install the Nikon udev rule. */
export const UDEV_COMMANDS = [
  'sudo cp docker/udev/99-nikon.rules /etc/udev/rules.d/',
  'sudo udevadm control --reload-rules',
  'sudo udevadm trigger',
].join('\n')
