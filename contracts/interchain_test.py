import unittest
import hashlib
from contracting.client import ContractingClient
from contracting.stdlib.bridge.time import Datetime, Timedelta
from contracting.stdlib.bridge.decimal import ContractingDecimal

class TestInterchain(unittest.TestCase):

    def setUp(self):
        # 1. Initialize a fresh ContractingClient
        self.c = ContractingClient()
        self.c.raw_driver.flush_full()

        with open("submission.s.py") as f:
            contract = f.read()
            self.c.raw_driver.set_contract(name="submission", code=contract)

        # 2. Deploy currency (assuming 'currency.py' is in the same directory)
        with open('currency.py') as f:
            code = f.read()
            self.c.submit(
                code,
                name='currency',
                constructor_args={'vk': 'sys'}  # 'sys' is the "manager" for currency
            )
        self.currency = self.c.get_contract('currency')

        # 3. Deploy the mailbox contract (assuming 'mailbox.py' is the name of your file)
        with open('mailbox.py') as f:
            code = f.read()
            self.c.submit(code, name='con_mailbox', signer='sys')


        # 4. Get references to the deployed mailbox contract
        self.mailbox = self.c.get_contract('con_mailbox')

        # 5. Deploy the interchain token contract
        with open('interchaintoken.py') as f:
            code = f.read()
            self.c.submit(
                code,
                name='con_interchain_token',
                constructor_args={
                    'domain': 1,
                    'router': 'router1',
                    'mailbox_contract': 'con_mailbox',
                    'interchain_router_contract': 'con_interchain_router'
                },
                signer='sys'
            )
        self.interchain_token = self.c.get_contract('con_interchain_token')

        # 6. Deploy the interchain token router contract
        with open('interchaintokenrouter.py') as f:
            code = f.read()
            self.c.submit(
                code,
                name='con_interchain_router',
                constructor_args={
                    'domain': 517164068468,
                    'mailbox_contract_name': 'con_mailbox'
                },
                signer='sys'
            )
        self.interchain_router = self.c.get_contract('con_interchain_router')


        # Give some test users currency
        # By default in the test environment, each user starts with 1,000,000 but let's top up 
        self.currency.transfer(amount=2000, to='user1', signer='sys')
        self.currency.transfer(amount=1000, to='user2', signer='sys')
        self.currency.transfer(amount=1000, to='sys', signer='sys')  # ensure sys also has enough

    def test_cross_chain_transfer(self):
        """
        Simulates bridging tokens from domain=1 -> domain=517164068468.
        
        We'll:
          1. Give user1 some local tokens (cheat by direct balance set).
          2. user1 calls xTransfer(...) -> burns locally + dispatch.
          3. Manually call the router.process(...) to simulate the cross-chain relayer.
          4. Router calls handleRemoteMint -> user2 gets minted tokens.
        """
        # 1) Check user1 has 1000 tokens
        self.c.raw_driver.set("con_interchain_token.balances:user1", 1000)
        self.assertEqual(self.interchain_token.balance_of(address='user1'), 1000)

        # 2) user1 calls xTransfer => burns 100 tokens => dispatch
        self.mailbox.setDispatchFee(amount=0, signer='sys')  # no fee for simplicity

        msg_id = self.interchain_token.xTransfer(
            destination_domain=517164068468,  # the router is on domain=517164068468
            recipient='user2',
            amount=float(100),
            signer='user1'
        )

        # After burning 100 tokens, user1 should have 400 left
        self.assertEqual(self.interchain_token.balance_of(address='user1'), 400)
        # A record of "burned" tokens is at balances['BRIDGE_BURNED'] for debugging
        self.assertEqual(self.interchain_token.balance_of(address='BRIDGE_BURNED'), 100)

        # 3) On the "destination chain", the router sees the event. We simulate that by
        #    calling router.process(...) in the same environment.
        #
        #    The router's `process` will do mailbox.process(...) and then call 
        #    interchain_token.handleRemoteMint(...) to mint 100 tokens for 'user2'.

        # We need the original message body. Usually it's the same string we passed
        # into mailbox.dispatch. However, 'xTransfer' built that. Let's get it from
        # the mailbox's `latestDispatchedId` or re-construct it:
        # We'll cheat & re-construct it, because we know how xTransfer encodes it:
        #   message_body = f"{ctx.caller}|{recipient}|{amount}|{localDomain}"
        
        message_body = f"user1|user2|100|1"

        # Now call router.process(...) 
        # The "message_id" is the same that xTransfer got from mailbox.dispatch
        self.interchain_router.process(
            message_body=message_body,
            message_id=msg_id,
            signer='sys',  # The relayer could be any address, we use 'sys' here
            environment={
                'block_num': 999  # for example
            }
        )

        # 4) Confirm user2 got minted 100 tokens
        self.assertEqual(self.interchain_token.balanceOf('user2'), 100)

        # Check that the mailbox's "delivered" status is True
        self.assertTrue(self.mailbox.delivered(msg_id))

        # Confirm we cannot process the same message again (router would try to re-process)
        with self.assertRaises(Exception) as cm:
            self.interchain_router.process(
                message_body=message_body,
                message_id=msg_id,
                signer='sys',
                environment={'block_num': 1000}
            )
        self.assertIn("Mailbox: already delivered", str(cm.exception))



if __name__ == '__main__':
    unittest.main()
