import { MongoClient, ServerApiVersion } from "mongodb";

if (process.argv.length != 5 && process.argv.length != 6) {
    console.error("!! ERROR !! Incorrect number of parameters.");
}

const MONGODB_SERVER = process.argv[2];
const MONGODB_PORT = process.argv[3];
// シナリオの DB 名（rism2 のシナリオDB。設定DB の demo_list の db_name）。省略時は demo_configs
const SCENARIO_DB = process.argv[5] || "demo_configs";

const uri = `mongodb://${MONGODB_SERVER}:${MONGODB_PORT}/`;
const client = new MongoClient(uri, {
    serverApi: {
        version: ServerApiVersion.v1,
        strict: true,
        deprecationErrors: true,
    },
});

const db_config = async () => {
    try {
        // Connect the client to the server
        await client.connect();
        // Send a ping to confirm a successful connection
        await client.db("admin").command({ ping: 1 });
        console.log(
            `Pinged your deployment. You successfully connected to MongoDB @ ${uri}`
        );
    } catch (err) {
        console.error(err);
    };
};

let scenario_db = client.db(SCENARIO_DB);

export { db_config, scenario_db, SCENARIO_DB }