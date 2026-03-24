import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const schemaPath = path.resolve(__dirname, "../../../schemas/task_envelope.schema.json");
const schema = JSON.parse(fs.readFileSync(schemaPath, "utf8"));

const ajv = new Ajv2020({
  allErrors: true,
  strict: false
});
addFormats(ajv);

const validateTaskEnvelopeSchema = ajv.compile(schema);

export function validateTaskEnvelope(taskEnvelope) {
  const valid = validateTaskEnvelopeSchema(taskEnvelope);

  return {
    valid,
    errors: valid ? [] : (validateTaskEnvelopeSchema.errors ?? [])
  };
}

export function assertValidTaskEnvelope(taskEnvelope) {
  const result = validateTaskEnvelope(taskEnvelope);

  if (!result.valid) {
    const message = result.errors
      .map((error) => `${error.instancePath || "/"} ${error.message}`)
      .join("; ");

    throw new Error(`Invalid TaskEnvelope: ${message}`);
  }

  return taskEnvelope;
}
