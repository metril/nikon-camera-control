/** Filesystems the Format dialog offers, with the per-filesystem label limit and a one-line note. */
export const FORMAT_FS = [
  {
    value: 'exfat',
    label: 'exFAT',
    max: 15,
    note: 'Works on Windows, Mac and Linux. Best default for photos and video.',
  },
  {
    value: 'fat32',
    label: 'FAT32',
    max: 11,
    note: 'Works on the oldest devices, but files are limited to 4 GiB.',
  },
  { value: 'ntfs', label: 'NTFS', max: 32, note: 'Windows; Macs can only read it.' },
  {
    value: 'ext4',
    label: 'ext4',
    max: 16,
    note: 'Most robust, but only this computer (Linux) can read it; Windows and Mac cannot.',
  },
]

/** Largest disk FAT32 may be used on (2 TiB less 1 MiB); the helper and API refuse more. */
export const FAT32_MAX_BYTES = 4294965248 * 512
export const FAT32_BIG_NOTE = 'Use exFAT for drives over 2 TB'
export const fsDisabled = (fstype, size) => fstype === 'fat32' && size > FAT32_MAX_BYTES

/** Mirrors the backend rule: ASCII letters, digits, space, _ and -; per-filesystem length. */
export function labelError(fstype, label) {
  const fs = FORMAT_FS.find((f) => f.value === fstype)
  if (!fs) return 'Choose a filesystem'
  if (label.length > fs.max) return `At most ${fs.max} characters for ${fs.label}`
  if (label && !/^[A-Za-z0-9_][A-Za-z0-9_ -]*$/.test(label))
    return "Use letters, digits, spaces, '_' and '-' only; do not start with '-' or a space"
  return ''
}
