## Scenario Switchboard for Indy

Enabling and disabling IndyXe's scenarios can be bothersome. It requires logging into the database, looking in the list of scenarios for the one you want to enable/disable, and change the status. If you have to do this multiple times, it can be quite boring.

So, I made this small Node.JS server that displays all Scenario names, along with their status as a toggle switch. Clicking on the toggle switch contacts the database to update the status instantly.

The best part is that once deployed it is very easy to use.

### Installation

**To install the server dependencies**, navigate to the `server` directory and type the following command:

```
npm install
```

### Configuration

Once the dependencies are installed, you can **run the project** from the same `server` directory. The Switchboard needs three parameters: the `MONGODB_URL`, `MONGODB_PORT`, and the `HTTP_PORT` that will be used to access the server, like so:

```
node server.js MONGODB_URL MONGODB_PORT HTTP_PORT
```

Once the server is running, from the host computer you can enter the address `http://localhost:HTTP_PORT` (With `HTTP_PORT` being the same as the one passed to `server.js`). This will display the Switchboard.