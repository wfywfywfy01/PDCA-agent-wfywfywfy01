export type SectionResult<T> =
  | { status: 'fulfilled'; value: T }
  | { status: 'rejected'; reason: unknown }

export async function loadSections<T>(
  loaders: Array<() => Promise<T>>,
  onResult: (index: number, result: SectionResult<T>) => void,
): Promise<SectionResult<T>[]> {
  return Promise.all(loaders.map(async (load, index) => {
    try {
      const result = { status: 'fulfilled' as const, value: await load() }
      onResult(index, result)
      return result
    } catch (reason) {
      const result = { status: 'rejected' as const, reason }
      onResult(index, result)
      return result
    }
  }))
}
