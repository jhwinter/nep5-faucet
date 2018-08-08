# nep5-faucet
A faucet for NEP-5 tokens on the NEO testnet.
This project was forked from https://github.com/CityOfZion/neo-faucet

## Docker Installation
0. Open a terminal
1. `cd nep5-faucet`
2. Complete necessary configurations in app/config/
3. `docker-compose up`
    * If it doesn't start running, it may be because docker sometimes likes to quit before allowing np-setup.exp 
    to finish bootstrapping the blockchain. I've tried everything that I can think of to make Docker stop doing this,
    but it still does it occasionally and I don't know why. If you have a solution that allows this to consistently 
    build and run, contributions are welcome.
4. Open a browser and go to http://localhost:8080 to visit the faucet web app

## If not using Docker, follow these Installation steps
0. Open a terminal
1. clone this repo
2. `cd nep5-faucet/app`
3. `python3 -m venv venv`
4. `source venv/bin/activate`
5. install requirements `pip3 install -r requirements.txt`
6. get a wallet on the NEO testnet with NEP-5 tokens in it 
7. Complete necessary configurations
    * if using venv, you may need to change a file path in faucet.py from `./src/neo-python` to `./venv/src/neo-python`
    * move config/.aws/* to ~/.aws/
    * modify config/nep5-token.json and config/environment.json 
8. start the faucet `python3 faucet.py`
9. Open a browser and go to http://localhost:8080 to visit the faucet web app


### Built using Docker Community Edition, Python 3.6.6, neo-python 0.7.6, and AWS Dynamodb
Engine: 18.03.1-ce <br/>
Compose: 1.21.1 (docker-compose file format v3.6)
