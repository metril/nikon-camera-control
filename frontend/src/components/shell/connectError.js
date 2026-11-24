/** Recognising "the camera is plugged in but the app may not open it" from a failed Connect. */

/** The backend's code for a Nikon USB node the app cannot open (HTTP 503). */
export const PERMISSION_CODE = 'CAMERA_PERMISSION_DENIED'

export const isNoPermission = (e) => e?.code === PERMISSION_CODE

/** What to run on the host to install the Nikon udev rule. */
export const UDEV_COMMANDS = [
  'sudo cp docker/udev/99-nikon.rules /etc/udev/rules.d/',
  'sudo udevadm control --reload-rules',
  'sudo udevadm trigger',
].join('\n')
