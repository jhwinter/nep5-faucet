#!/usr/bin/env python3

"""
Authors: Jonathan Winter
Email: jonathan@splyse.tech
Version: 0.2
Date: 07 August 2018
License: MIT

This project was forked from https://github.com/CityOfZion/neo-faucet

Minimal NEO node with custom code in a background thread.
It will log events from all smart contracts on the blockchain
as they are seen in the received blocks.
This project uses the minimal NEO node to keep up to date with 
neo blocks and to transfer user-specified NEP5 tokens.
"""

# built-in packages
import os
import struct
import json
from datetime import datetime, timedelta
import logging
from pathlib import Path
import subprocess
from time import time, sleep

# third-party packages
from logzero import logger, setup_logger
from twisted.internet import task
from twisted.internet.defer import succeed
from klein import Klein
from jinja2 import FileSystemLoader, Environment, select_autoescape
from neo.Core.TX.InvocationTransaction import InvocationTransaction
from neo.Core.Blockchain import Blockchain
from neo.Core.TX.TransactionAttribute import TransactionAttribute, TransactionAttributeUsage
from neo.Core.Helper import Helper
from neo.Implementations.Blockchains.LevelDB.LevelDBBlockchain import LevelDBBlockchain
from neo.Implementations.Wallets.peewee.UserWallet import UserWallet
from neo.Network.NodeLeader import NodeLeader
from neo.Prompt.Commands.Invoke import InvokeContract, TestInvokeContract
from neo.Settings import settings
from neo.Wallets.utils import to_aes_key
from neo.VM.OpCode import *
from neocore.BigInteger import BigInteger
from neocore.Fixed8 import Fixed8

# local packages
from db_models import FaucetRequest, IPRequest

# logfile settings & setup
LOGFILE_FILENAME = './logs/faucet.log'
LOGFILE_MAX_BYTES = 10000000  # 1e7 or 10 MB
LOGFILE_BACKUP_COUNT = 3  # 3 logfiles history
settings.set_logfile(fn=LOGFILE_FILENAME, max_bytes=LOGFILE_MAX_BYTES, backup_count=LOGFILE_BACKUP_COUNT)

# extra logfile settings & setup
logger_request = setup_logger(name='logger_request',
                              logfile='./logs/request.log',
                              level=logging.INFO,
                              maxBytes=LOGFILE_MAX_BYTES,
                              backupCount=LOGFILE_BACKUP_COUNT)


class ItemStore(object):
    """ Houses pretty much everything pertaining to the actual faucet """
    Wallet = None
    app = Klein()

    j2_env = Environment(loader=FileSystemLoader('templates'), autoescape=select_autoescape(['html']), trim_blocks=True)

    OPERATION = 'transfer'

    def __init__(self):
        """
        initializes the database by calling the create_tables method; redeclares the contract hash (for redundancy);
        initializes variables that are needed to get the faucet instance running as well as pass data to the smart
        contract; sets up the wallet; checks the height of the blockchain and compares it to the block height of the
        wallet, if they are not equivalent, it processes new blocks until they are

        """
        self._create_tables()
        self.params = []
        self.invoke_args = []
        self.sent_tx = None

        self.token_name = os.environ.get('TOKEN_NAME')
        self.token_symbol = os.environ.get('TOKEN_SYMBOL')
        self.token_script_hash = os.environ.get('TOKEN_SCRIPT_HASH')
        if self.token_name is None or self.token_symbol is None or self.token_script_hash is None:
            raise Exception('Please set TOKEN_NAME, TOKEN_SYMBOL, and TOKEN_SCRIPT_HASH in ./config/nep5-token.json')

        wallet_path = os.environ.get('FAUCET_WALLET_PATH')
        wallet_pwd = to_aes_key(os.environ.get('FAUCET_WALLET_PASSWORD'))
        self.faucet_wallet_addr = os.environ.get('FAUCET_WALLET_ADDRESS')
        if wallet_pwd is None or wallet_path is None or self.faucet_wallet_addr is None:
            raise Exception('Please set FAUCET_WALLET_PATH, FAUCET_WALLET_PASSWORD, and FAUCET_WALLET_ADDRESS '
                            'in ./config/environment.json')

        self.wallet = UserWallet.Open(path=wallet_path, password=wallet_pwd)

        dbloop = task.LoopingCall(self.wallet.ProcessBlocks)  # specifies what function to call
        dbloop.start(.1)  # every 0.1 seconds, self.wallet.ProcessBlocks function is called

        self.wallet.Rebuild()
        self.wallet._current_height = 100000  # is this arbitrary or is there a specific reason to set at this height?
        logger.info(f'created wallet: {self.wallet.ToJson()}')

    @staticmethod
    def _create_tables():
        """ Creates the FaucetRequest and IPRequest tables in the DynamoDB database if they don't already exist """
        if not FaucetRequest.exists():
            FaucetRequest.create_table(wait=True)
        if not IPRequest.exists():
            IPRequest.create_table(wait=True)

    def _get_context(self):
        """
        Function loads all of the NEP5 tokens stored in the faucet's wallet, then gets the amount of NEP5 tokens with
        the specified script hash

        :return: a json object containing the blockchain's block height, amount of user-specified NEP5 tokens
        in the wallet, and the current wallet height
        """
        tokens = self.wallet.LoadNEP5Tokens()  # loads all nep-5 tokens from the faucet's wallet
        token_balance = self.wallet.GetTokenBalance(token=tokens.get(self.token_script_hash.encode('utf-8')))
        if token_balance is None:
            token_balance = BigInteger(0)

        return {
            'message': 'Welcome to NEP-5 Faucet',
            'faucet_wallet': self.faucet_wallet_addr,
            'height': Blockchain.Default().Height,
            'wallet_height': self.wallet.WalletHeight,
            f'{self.token_symbol}': int(token_balance),
            'token_name': self.token_name,
            'token_symbol': self.token_symbol,
            'token_script_hash': self.token_script_hash
        }

    def _make_tx(self, address_to):
        """
        Function that creates the parameters for the NEP-5 transfer function and then calls it,
        returning the transaction info

        :param address_to: address to send the tokens to
        :return:
            transaction info
        """
        drip_amount = BigInteger(10000)
        amount = BigInteger(drip_amount * 100000000)  # must multiply by Fixed8.D and must be BigInteger object
        self.invoke_args.clear()
        self.params.clear()  # make sure that invoke_args and params lists are empty
        scripthash_from = Helper.AddrStrToScriptHash(address=self.faucet_wallet_addr).ToArray()
        scripthash_to = address_to

        self.invoke_args.append(scripthash_from)
        self.invoke_args.append(scripthash_to)
        self.invoke_args.append(amount)
        self.params = [self.token_script_hash.encode('utf-8'), self.OPERATION, self.invoke_args]
        nonce = struct.pack('>i', int(time()))  # convert the int to a big endian int
        # the int(time()) is the time in seconds since the epoch (01/01/1970 for UNIX systems)
        # the nonce was used to append to the TransactionAttribute so that each transaction has slightly
        # different data. Otherwise, each transaction would constantly be given the same transaction hash because
        # all of their parameters are the same
        # TransactionAttributeUsage.Remark is b'\xf0' = 240
        invoke_attributes = [TransactionAttribute(usage=TransactionAttributeUsage.Remark, data=nonce)]
        # the following test invokes the contract (useful to ensure that noting is wrong)
        tx, fee, results, num_ops = TestInvokeContract(wallet=self.wallet,
                                                       args=self.params,
                                                       from_addr=self.faucet_wallet_addr,
                                                       min_fee=Fixed8.Zero(),
                                                       invoke_attrs=invoke_attributes)

        # the following is just used for logging info
        if tx is not None and results is not None:
            logger.info('\n------------------------')
            for item in results:
                logger.info(f'Results: {str(item)}')
                if not len(str(item)) % 2:
                    try:
                        logger.info(f'Hex decode: {binascii.unhexlify(str(item))}')
                    except Exception:
                        logger.warning('Not hex encoded')
            logger.info(f'Invoke TX gas cost: {(tx.Gas.value / Fixed8.D)}')
            logger.info(f'Invoke TX Fee: {(fee.value / Fixed8.D)}')
            logger.info('Relaying invocation tx now')
            logger.info('------------------------\n')

        # invoke the contract
        self.sent_tx = InvokeContract(wallet=self.wallet, tx=tx, fee=Fixed8.Zero(), from_addr=self.faucet_wallet_addr)
        sleep(3)  # allow a few seconds for the contract to be invoked and return the tx info is actually passed
        return self.sent_tx

    @app.route('/')
    @app.route('/index')
    def index(self, request):
        """
        index page for the faucet site

        :param request: klein Request object that gets passed into every route function
        :return: the rendered index template containing the context

        """
        ctx = self._get_context()
        if ctx[f'{self.token_symbol}'] < 10000:
            logger.warning('NO ASSETS AVAILABLE')
            ctx['error'] = True
            ctx['message'] = 'NO ASSETS AVAILABLE. Come back later.'
            ctx['come_back'] = True
        output = self.j2_env.get_template('index.html').render(ctx)
        return output

    @app.route('/ask', methods=['POST'])
    def ask_for_assets(self, request):
        """
        This function processes the user input; creates and saves the user's IP address and time of their visit and
        their wallet address and time of their visit; if the user's information checks out and they haven't visited
        too many times, then it will send their information to the _make_tx_ function. Upon success, it will redirect
        the user to the success page and display the transaction info

        :param request: klein request object that gets passed into every route function
        :return: upon success, returns a Deferred that already had '.callback(result)' called
        upon failure, returns the index page with some error displayed

        """
        self.sent_tx = None
        ctx = self._get_context()
        ctx['error'] = False
        proceed = True
        step = 0
        iprequest_item = None
        faucetrequest_item = None
        address_to = None
        now = datetime.now()
        past_week = now - timedelta(days=7)
        #next_week = now + timedelta(days=7)  # for testing
        epochTs = time()  # the time() is the time in seconds since the epoch (01/01/1970 for UNIX systems)
        week_in_sec = 60 * 60 * 24 * 7  # 60 seconds * 60 minutes * 24 hours * 7 days
        expire_date = epochTs + week_in_sec

        if ctx[f'{self.token_symbol}'] < 10000:
            request.redirect('/')
            return succeed(None)
        try:
            if b'address_to' in request.args:
                address_to = request.args.get(b'address_to')[0].decode('utf-8').strip()
                ctx['address_to'] = address_to
                client = None

                if (proceed is True) & (step == 0):  # for IPRequest
                    #client = str(request.getClientAddress().host)  # gets the IPv4 address
                    client = str(request.getHeader(key='x-real-ip'))  # gets the IPv4 address if behind NGINX server
                    iprequest_item = IPRequest(ip_address=client,
                                               last_visited=now,
                                               ttl=expire_date)  # creates IPRequest item
                    count = 0  # the following gets all requests from this ip address in the past week
                    for item in IPRequest.query(hash_key=client,
                                                range_key_condition=IPRequest.last_visited > past_week,
                                                limit=10):
                        count += 1

                    logger_request.info(f'IPRequest TOTAL: {count}')
                    if count >= 3:  # if user(s) from this ip has requested >= 3 times in the past week,
                        proceed = False  # stop progress for the program
                        ctx['message'] = 'You have requested too many times for this time period. ' \
                                         'Try again next week.'  # display error message
                        ctx['error'] = True
                    else:  # else go to the next step
                        step += 1
                elif (proceed is True) & (step == 0):
                    ctx['error'] = True
                    ctx['message'] = 'Request failed. Please try again.'

                if (proceed is True) & (step == 1):  # for FaucetRequest
                    faucetrequest_item = FaucetRequest(wallet_address=address_to,
                                                       last_visited=now,
                                                       ttl=expire_date)  # creates FaucetRequest item
                    count = 0  # the following gets all requests from this wallet address in the past week
                    for item in FaucetRequest.query(hash_key=address_to,
                                                    range_key_condition=FaucetRequest.last_visited > past_week,
                                                    limit=10):
                        count += 1

                    logger_request.info(f'FaucetRequest TOTAL: {count}')
                    if count >= 1:  # if user from this wallet address has requested >= 1 times in the past week,
                        proceed = False  # stop progress for the program
                        ctx['message'] = 'Already requested within the past week'  # display error message
                        ctx['error'] = True
                    else:  # else save the request to the database
                        iprequest_item.save()
                        faucetrequest_item.save()
                        step += 1
                        logger_request.info('\n----------------------------')
                        logger_request.info(f'IP Address: {client}')
                        logger_request.info(f'Wallet Address: {address_to}')
                        logger_request.info(f'Date of Request: {now}')
                        logger_request.info('----------------------------\n')
                elif (proceed is True) & (step == 1):
                    ctx['error'] = True
                    ctx['message'] = 'Request failed. Please try again.'

                if (proceed is True) & (step == 2):  # make transaction
                    tx = self._make_tx(Helper.AddrStrToScriptHash(address=address_to).ToArray())

                    # neo-faucet used ContractTransaction() for this part because they created a smart contract to
                    # transfer the system assets.
                    # Since this is a nep5 token faucet, we use InvocationTransaction() to invoke the token's
                    # 'transfer' function.
                    if type(tx) is InvocationTransaction:
                        logger.info('ALL OK!!!')
                        step = 0
                        self.sent_tx = tx  # sets the objects instance variable sent.tx to the tx info
                        request.redirect('/success')  # redirects to the success page
                        return succeed(None)
                    else:
                        ctx['message'] = f'Error constructing transaction: {tx}'
                        ctx['error'] = True
                else:
                    if ctx['message'] is None:
                        ctx['message'] = 'You must input a wallet address to proceed'
                        ctx['error'] = True
        except Exception as e:
            logger_request.error(f'exception: {e}')
            ctx['error'] = True
            ctx['message'] = f'Could not process request: {e}'

        output = self.j2_env.get_template('index.html').render(ctx)
        return output

    @app.route('/success')
    def app_success(self, request):
        """

        :param request: klein request object that gets passed into every route function
        :returns: param request:

        """
        ctx = self._get_context()
        if not self.sent_tx:  # error checking
            logger.info('NO SENT TX:')
            request.redirect('/')
            return succeed(None)

        senttx_json = json.dumps(self.sent_tx.ToJson(), indent=4)
        ctx['tx_json'] = senttx_json
        ctx['message'] = f'Your request has been relayed to the network. Transaction: {self.sent_tx.Hash.ToString()}'
        output = self.j2_env.get_template('success.html').render(ctx)

        self.sent_tx = None  # resets the instance variable
        self.wallet.Rebuild()  # update wallet
        self.wallet._current_height = 100000  # still don't understand why this block height is so special
        return output


def init_environ(filename_faucet, filename_token, filename_protocol):
    """
    Initializes faucet configuration information, protocol configuration information, and token configuration info
    :param filename_faucet: json file to config faucet info -- environment.json
    :param filename_protocol: json file to config protocol info -- ./src/neo-python/neo/data/protocol.testnet.json
    :param filename_token: json file to config NEP5 token info  -- nep5-token.json
    :return: True
    """
    with open(filename_faucet, 'r') as faucet:
        faucet_data = json.load(faucet)

    os.environ['FAUCET_WALLET_PATH'] = faucet_data['FAUCET_WALLET_PATH']
    os.environ['FAUCET_WALLET_ADDRESS'] = faucet_data['FAUCET_WALLET_ADDRESS']
    os.environ['FAUCET_WALLET_PASSWORD'] = faucet_data['FAUCET_WALLET_PASSWORD']
    os.environ['FAUCET_PORT'] = faucet_data['FAUCET_PORT']
    os.environ['FAUCET_HOST'] = faucet_data['FAUCET_HOST']

    # user-specified token name, symbol, and script hash
    with open(filename_token, 'r') as token:
        token_data = json.load(token)

    os.environ['TOKEN_NAME'] = token_data['TOKEN_NAME']
    os.environ['TOKEN_SYMBOL'] = token_data['TOKEN_SYMBOL']
    os.environ['TOKEN_SCRIPT_HASH'] = token_data['TOKEN_SCRIPT_HASH']

    # The app breaks if I don't change the json data and notification paths
    # to specifically be /root/.neopython/Chains/*
    # so, while certainly not very elegant, this is my solution
    with open(filename_protocol, 'r') as protocol:
        proto_data = json.load(protocol)

    proto_data['ApplicationConfiguration']['DataDirectoryPath'] = f'{Path.home()}/.neopython/Chains/SC234'
    proto_data['ApplicationConfiguration']['NotificationDataPath'] = f'{Path.home()}/.neopython/Chains/Test_Notif'

    with open(filename_protocol, 'w') as protocol:
        json.dump(proto_data, protocol)

    return True


def main():
    """ """
    # check to see if the chains already exist
    if not os.path.isdir(f'{Path.home()}/.neopython/Chains/SC234'):
        subprocess.call(['expect', './config/np-setup.exp'])

    # Setup the blockchain with logging smart contract events turned on
    settings.set_log_smart_contract_events(True)  # uncomment if you want to be spammed with notifications

    # initialize environment, nep5-token, and testnet protocol
    init_environ('./config/environment.json',
                 './config/nep5-token.json',
                 './src/neo-python/neo/data/protocol.testnet.json')
    settings.setup('./src/neo-python/neo/data/protocol.testnet.json')  # use testnet protocol file

    # Instantiate the blockchain and subscribe to notifications
    blockchain = LevelDBBlockchain(settings.LEVELDB_PATH)
    Blockchain.RegisterBlockchain(blockchain)

    # add blocks to the blockchain every 0.1 seconds
    dbloop = task.LoopingCall(Blockchain.Default().PersistBlocks)
    dbloop.start(.1)
    NodeLeader.Instance().Start()

    # configure and run faucet web app on the specified host and port
    host = os.environ.get('FAUCET_HOST', 'localhost')
    port = os.environ.get('FAUCET_PORT', 80)
    store = ItemStore()
    store.app.run(host=host, port=port)

    logger.info('Shutting down.')


if __name__ == "__main__":
    main()
