import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../src/agent/session-view.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { requestCount, sessionOutcome, duration } = await import(
    'data:text/javascript;base64,' + Buffer.from(compiled).toString('base64')
);
test('session counts failed and in-flight attempts without inventing billed tokens', () => {
    assert.equal(
        requestCount({
            usage: { calls: 0 },
            records: [{ kind: 'model_request', status: 'error' }],
        }),
        1,
    );
    assert.equal(
        requestCount({
            usage: { calls: 2 },
            records: [
                { kind: 'model_request', status: 'done' },
                { kind: 'model_request', status: 'done' },
                { kind: 'model_request', status: 'running' },
            ],
        }),
        3,
    );
    assert.equal(requestCount({ usage: { calls: 3 } }), 3, 'old records retain their known usage');
});
test('session result keeps actual sends separate from later failure or cancellation', () => {
    assert.equal(sessionOutcome({ status: 'error', sent: [{}] }), '已发送，后续处理异常');
    assert.equal(sessionOutcome({ status: 'aborted', sent: [{}] }), '已发送，处理已停止');
    assert.equal(sessionOutcome({ status: 'error', sent: [] }), '处理失败');
    assert.equal(duration({ started: 1000, ended: 1200 }), '0.2 秒');
    assert.equal(duration({ started: 1000, ended: null }), '');
});
