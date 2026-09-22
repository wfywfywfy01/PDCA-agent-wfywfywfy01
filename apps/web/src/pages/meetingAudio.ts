export function audioHref(link: Record<string, unknown>): string {
  return String(link.audio_url ?? link.url ?? link.play_url ?? '')
}

export function meetingAudioFor(
  links: Record<string, unknown>[],
  meetingId: string,
): Record<string, unknown>[] {
  return links.filter((link) => String(link.meeting_id ?? '') === meetingId)
}

export function meetingDate(row: Record<string, unknown>, fallback: string): string {
  return String(row.date ?? row.start_time ?? fallback).slice(0, 10)
}
