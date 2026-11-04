
import express from "express";

const router = express.Router({ mergeParams: true });

import { ltm_db, sm_db, stm_db } from "./db.js";

// Get all Dialogue entires starting from t0
router.get("/chat/:t0/:tf", async (req, res) => {
  let sm_coll = sm_db.collection("dia");
  let query = { created_at_ts: { $gte: Number(req.params.t0), $lt: Number(req.params.tf) } };
  // console.log(query);
  let query_options = {
    projection: { _id: 1, actor: 1, utterance: 1, created_at_ts: 1 }
  };
  let results = await sm_coll.find(query, query_options).toArray();
  if (results.length > 0) {
    console.log(`[CHAT] Served ${results.length} results.`);
  }
  res.send(results).status(200);
});

var latest_id = "";
router.get("/chatlatest/", async (req, res) => {
  let sm_coll = sm_db.collection("dia");
  let query_options = {
    sort: { created_at_ts: -1 },
    projection: { _id: 1, actor: 1, utterance: 1, created_at_ts: 1 }
  };
  let results = await sm_coll.findOne({}, query_options);
  while (!results) {
    results = await sm_coll.findOne({}, query_options);
  }
  res.send(results).status(200);
});

// Get STM and LTM from the last hour since t0
router.get("/memory/:t0", async (req, res) => {
  let tf = Number(req.params.t0);
  let t0 = tf - 3600.0;
  console.log(`[MEMORY] From ${t0} to ${tf}`);

  let stm_coll = stm_db.collection("dia");
  let ltm_coll = ltm_db.collection("narrative");
  let query = { created_at_ts: { $gte: t0, $lte: tf }, "forgetting_curve.forget_time": { $gte: tf } };
  let stm_results = await stm_coll.find(query).toArray();

  let ltm_options = {
    projection: { embedding: 0, participants: 0 }
  };
  let ltm_results = await ltm_coll.find(query, ltm_options).toArray();

  console.log(`[STM] Served ${stm_results.length} results.`);

  // console.log(`==  SHORT-TERM MEMORIES @ ${req.params.t0}  ==`)
  // narr_results.forEach((mem) => {
  //   var c_string = `[${mem['type']}] ${mem['memory']}`;
  //   if (c_string.length > 103) {
  //     c_string = c_string.substring(0, 100) + "...";
  //   }
  //   console.log(c_string);
  // });

  console.log(`[LTM] Served ${ltm_results.length} results.`);

  // console.log(`==  LONG-TERM MEMORIES @ ${req.params.t0}  ==`)
  // ltm_results.forEach((mem) => {
  //   var c_string = `[LTM] ${mem['today_summ']}`;
  //   if (c_string.length > 103) {
  //     c_string = c_string.substring(0, 100) + "...";
  //   }
  //   console.log(c_string);

  // });


  res.send({ "stm": stm_results, "ltm": ltm_results }).status(200);
});

export default router;