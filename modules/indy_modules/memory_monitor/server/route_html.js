import express from "express";
import fs from "fs";
import path from "path";

const router = express.Router({ mergeParams: true });

import { dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Base directory for Web files
const WWW_DIR = "www";

function res_handler(p, res) {
  // Check existance, return 404 if file does not exist
  if (fs.existsSync(p)) {
    res.sendFile(p, { root: __dirname });
  } else {
    res.status(404);
  }
}

router.get("/", (req, res) => {
  res_handler(path.join(WWW_DIR, "index.html"), res);
});

// These are the only valid directories for HTML requests.
// They are all under WWW_DIR
router.get("/styles/:file", (req, res) => {
  res_handler(path.join(WWW_DIR, "styles", req.params.file), res);
});

router.get("/chat-bubble/:file", (req, res) => {
  res_handler(path.join(WWW_DIR, "chat-bubble", req.params.file), res);
});

router.get("/chat-bubble/:subdir/:file", (req, res) => {
  res_handler(path.join(WWW_DIR, "chat-bubble", req.params.subdir, req.params.file), res);
});
router.get("/fonts/notojp.ttf", (req, res) => {
  res_handler(path.join(WWW_DIR, "fonts", "notojp", "NotoSansJP-VariableFont_wght.ttf"), res);
});

export default router;