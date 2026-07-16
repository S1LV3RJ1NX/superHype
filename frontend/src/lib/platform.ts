export const PLATFORM_LABEL: Record<string, string> = {
  linkedin: "LinkedIn",
  x: "X",
};

export function platformLabel(platform: string | null | undefined): string {
  return PLATFORM_LABEL[platform ?? "linkedin"] ?? "LinkedIn";
}
