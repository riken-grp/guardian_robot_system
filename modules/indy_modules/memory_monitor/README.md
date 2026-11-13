## Visualizer for Indy's Narrative Memory

This visualizer shows Indy's Conversations, Narrative and Long-Term Memories. It must be run after the Memory System. 

It runs on a Node.js express server.

**To install the server dependencies**, navigate to the `server` directory and type the following command:

```
npm install
```

### Configuration

Once the dependencies are installed, you can **run the project** from the same `server` directory. The Visualizer needs three parameters: the `MONGODB_URL`, `MONGODB_PORT`, and the `HTTP_PORT` that will be used to access the server, like so (`MONGODB_URL` is the host name or IP address of the MongoDB server, without `mongodb://`; the server builds `mongodb://MONGODB_URL:MONGODB_PORT/` from it):

```
node server.js MONGODB_URL MONGODB_PORT HTTP_PORT
```

Once the server is running, from the host computer you can enter the address `http://localhost:HTTP_PORT` (With `HTTP_PORT` being the same as the one passed to `server.js`). This will display the visualizer. Do note that the visualizer does not show historical data, only the memories generated since the visualizer loads on the browser are displayed.

The directories and files that can be accessed are limited to those used in the interface + backend calls. 

- If you want to customize the interface with files and directories in the `www` directory, you may have to add them manually to the server routing script in `server/route_html.js`. 
- If you want to add more endpoints for backend calls, you can either create a new route file, or add them to `route_mongodb.js`.

As for the chat interface, it is based off this [chat-bubble](https://github.com/dmitrizzle/chat-bubble/) package. Check their documentation for more options.