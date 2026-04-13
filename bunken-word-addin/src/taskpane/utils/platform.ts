export function isMacPlatform() {
  return Office.context.platform === Office.PlatformType.Mac;
}

export function isWindowsPlatform() {
  return Office.context.platform === Office.PlatformType.PC;
}
