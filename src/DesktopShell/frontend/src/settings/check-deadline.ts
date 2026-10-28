export class CheckDeadlineError extends Error {
    constructor() {
        super('检查未在等待时限内返回，请稍后手动重试。');
    }
}

/** Stop waiting for a lost bridge acknowledgement; never retry the request. */
export async function waitForCheck<T>(work: T, timeoutMs: number): Promise<Awaited<T>> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
        return await Promise.race([
            Promise.resolve(work),
            new Promise<never>((_, reject) => {
                timer = setTimeout(() => reject(new CheckDeadlineError()), timeoutMs);
            }),
        ]);
    } finally {
        clearTimeout(timer);
    }
}
