import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { scanDeployableBytes } from "../scripts/stage14-bundle-scan.mjs";

for (const name of ["creative-bulb", "home-cosmos", "manuscript-glass", "story-door"]) {
  test(`reviewed ${name} provenance passes, mutations and exact secrets do not`, async () => {
    const bytes = await readFile(new URL(`../public/assets/v140/${name}.png`, import.meta.url));
    assert.equal(bytes.subarray(0, 8).toString("hex"), "89504e470d0a1a0a");
    let offset = 8;
    let emails = 0;
    while (offset < bytes.length) {
      const length = bytes.readUInt32BE(offset);
      const type = bytes.toString("ascii", offset + 4, offset + 8);
      const data = bytes.subarray(offset + 8, offset + 8 + length);
      const matches = [...data.toString("utf8").matchAll(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/ig)];
      if (matches.length) {
        assert.equal(type, "caBX");
        assert.ok(matches.every((match) => match[0] === "ca@trufo.ai"));
        // DER PKCS#9 emailAddress OID + IA5String value in CA certificates.
        const certificateEmail = Buffer.from("06092a864886f70d010901160b636140747275666f2e6169", "hex");
        assert.equal(data.toString("hex").split(certificateEmail.toString("hex")).length - 1, matches.length);
        assert.ok(data.includes(Buffer.from("Trufo C2PA")));
        emails += matches.length;
      }
      offset += 12 + length;
    }
    assert.ok(emails > 0);
    assert.doesNotThrow(() => scanDeployableBytes(bytes));
    assert.throws(() => scanDeployableBytes(Buffer.concat([bytes, Buffer.from("changed")])), /EMAIL_HIT/);
    assert.throws(() => scanDeployableBytes(bytes, [], ["ca@trufo.ai"]), /SECRET_HIT/);
  });
}
test("CA email is not generally allowlisted in source or unknown image data", () => {
  assert.throws(() => scanDeployableBytes(Buffer.from("ca@trufo.ai")), /EMAIL_HIT/);
  assert.throws(() => scanDeployableBytes(Buffer.from("writer@example.test")), /EMAIL_HIT/);
});
