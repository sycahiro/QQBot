const fs = require('node:fs');
const semver = require(process.argv[2]);
const manifest = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const range = manifest.engines && manifest.engines.node;
if (range && !semver.satisfies(process.version, range)) {
    console.error(`SnowLuma requires Node ${range}; installed ${process.version}`);
    process.exitCode = 1;
}
