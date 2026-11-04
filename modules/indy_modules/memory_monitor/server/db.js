import { MongoClient, ServerApiVersion } from "mongodb";

if (process.argv.length != 5) {
    console.error("!! ERROR !! Incorrect number of parameters.");
}

const MONGODB_SERVER = process.argv[2];
const MONGODB_PORT = process.argv[3];

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

let sm_db = client.db("sensor_memory");
let stm_db = client.db("short_term_memory");
let ltm_db = client.db("long_term_memory");

export { db_config, ltm_db, sm_db, stm_db };