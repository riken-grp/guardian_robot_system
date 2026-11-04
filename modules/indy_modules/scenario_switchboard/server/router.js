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

router.get("/:file", (req, res) => {
    res_handler(path.join(WWW_DIR, req.params.file), res);
});

router.get("/css/:file", (req, res) => {
    res_handler(path.join(WWW_DIR, "css", req.params.file), res);
});

/* MONGODB STUFF */

import { rism_configs } from "./db.js";
import { ObjectId } from "mongodb";

router.get("/api/data", async (req, res) => {
    try {
        let coll_sce = rism_configs.collection("scenarios");
        let coll_sub = rism_configs.collection("interruption_subscenarios");
        let projectFields = { _id: 1, name: 1, status: 1 };
        let scenarios = await coll_sce.find().project(projectFields).toArray();
        let subscenarios = await coll_sub.find().project(projectFields).toArray();

        let data = { scenarios: scenarios, subscenarios: subscenarios };

        res.json(data).status(200);
    } catch (err) {
        console.error("Database Error: ", err);
        res.status(500).json({ error: "Internal server error" });
    }
});


router.post("/api/toggle", async (req, res) => {
    try {
        const { id, scenario_type, status } = req.body;

        let coll_name = (scenario_type === "scenario" ? "scenarios" : "interruption_subscenarios");
        let coll = rism_configs.collection(coll_name);
        let filter = { _id: ObjectId.createFromHexString(id) };
        let update = { $set: { status: status } };
        let updated = await coll.updateOne(filter, update);

        let data = { id: id, modified: true };

        if (updated.modifiedCount == 0) {
            data.modified = false;
        }

        res.json(data).status(200);

    } catch (err) {
        console.error("Database Error: ", err);
        res.status(500).json({ error: "Internal server error" });
    }
});

export default router