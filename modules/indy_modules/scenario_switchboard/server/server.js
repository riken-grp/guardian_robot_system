import cors from "cors";
import express from "express";
import www from "./router.js";

if (process.argv.length != 5) {
    console.error("!! ERROR !! Incorrect number of parameters.");
}

const HTTP_PORT = parseInt(process.argv[4]);

import { db_config } from "./db.js";

const express_app = express();

express_app.use(cors());
express_app.use(express.json());

db_config();

express_app.use("/", www);

// start the Express server
express_app.listen(HTTP_PORT, () => {
    console.log(`Server listening on port ${HTTP_PORT}`);
});