import cors from "cors";
import express from "express";
import html from "./route_html.js";
import mongodb from "./route_mongodb.js";

if (process.argv.length != 5) {
  console.error("!! ERROR !! Incorrect number of parameters.");
}

const HTTP_PORT = parseInt(process.argv[4]);

import { db_config } from "./db.js";

const express_app = express();

express_app.use(cors());
express_app.use(express.json());

db_config();

express_app.use("/", html);
express_app.use("/db", mongodb);

// start the Express server
express_app.listen(HTTP_PORT, () => {
  console.log(`Server listening on port ${HTTP_PORT}`);
});