import unittest
import hashlib
from contracting.client import ContractingClient
from contracting.stdlib.bridge.time import Datetime, Timedelta

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
        self.currency.transfer(amount=1000, to='user1', signer='sys')
        self.currency.transfer(amount=1000, to='user2', signer='sys')
        self.currency.transfer(amount=1000, to='sys', signer='sys')  # ensure sys also has enough

    def test_owner_set_fee(self):
        """
        Tests that the owner (sys) can set a dispatch fee.
        """
        # Initially, dispatchFee should be 0
        self.assertEqual(self.mailbox.getDispatchFee(), 0)  # or 0 if your default is 0

        # Owner sets fee
        self.mailbox.setDispatchFee(amount=10, signer='sys')
        self.assertEqual(self.mailbox.getDispatchFee(), 10)

    def test_non_owner_cannot_set_fee(self):
        """
        Tests that a non-owner cannot set a dispatch fee.
        """
        with self.assertRaises(Exception) as cm:
            self.mailbox.setDispatchFee(amount=50, signer='user1')
        self.assertIn("Only the contract owner can call this method", str(cm.exception))

    def test_dispatch_without_fee(self):
        """
        Tests dispatch behavior when fee is zero or not set yet.
        """
        # Ensure there's no dispatch fee
        self.mailbox.setDispatchFee(amount=0, signer='sys')

        # user1 calls dispatch
        msg_id = self.mailbox.dispatch(
            destination_domain=9999,
            recipient_address='someRecipient',
            message_body='hello cross-chain!',
            signer='user1'
        )
        self.assertIsNotNone(msg_id)

        # Check that the nonce incremented
        self.assertEqual(self.mailbox.nonce.get(), 1)
        # The contract’s latestDispatchedId should match msg_id
        self.assertEqual(self.mailbox.latestDispatchedId.get(), msg_id)

        # Because fee=0, user1's balance should remain at 1001000
        self.assertEqual(self.currency.balance_of(account='user1'), 1001000)

    def test_dispatch_with_fee(self):
        """
        Tests dispatch behavior when a dispatch fee is set.
        """
        # Owner sets dispatch fee = 50
        self.mailbox.setDispatchFee(amount=50, signer='sys')

        # user1 must approve the mailbox to take 50 currency on dispatch
        self.currency.approve(amount=50, to='con_mailbox', signer='user1')

        # user1 calls dispatch
        msg_id = self.mailbox.dispatch(
            destination_domain=4321,
            recipient_address='recipientX',
            message_body='fee test message',
            signer='user1'
        )
        self.assertIsNotNone(msg_id)

        self.assertEqual(self.currency.balance_of(account='user1'), 1000950)
        self.assertEqual(self.currency.balance_of(account='sys'), 998050)

    def test_process_message(self):
        """
        Tests processing a message that was dispatched.
        """
        # 1. Dispatch a message
        self.mailbox.setDispatchFee(amount=0, signer='sys')
        msg_id = self.mailbox.dispatch(
            destination_domain=555,
            recipient_address='mockRecipient',
            message_body='payload',
            signer='user1'
        )

        # 2. Process the message
        # We'll cheat a bit and pass arbitrary metadata, 
        # since there's no real bridging verification in this example
        self.mailbox.process(
            metadata='testMetadata',
            message_id=msg_id,
            signer='user2',
            environment={
                'block_num': 1234
            }
        )

        # 3. Check that the message is marked delivered
        self.assertTrue(self.mailbox.delivered(message_id=msg_id))
        # Processor should be user2
        self.assertEqual(self.mailbox.processor(message_id=msg_id), 'user2')

        # If we call process again, we should fail
        with self.assertRaises(Exception) as cm:
            self.mailbox.process(
                metadata='testMetadata',
                message_id=msg_id,
                signer='user2',
                environment={
                    'block_num': 1234
                }
            )
        self.assertIn("Mailbox: already delivered", str(cm.exception))

    def test_delivered_and_processor_before_process(self):
        """
        Tests that a message is not delivered before it's actually processed, 
        and that the processor is None.
        """
        msg_id = self.mailbox.dispatch(
            destination_domain=100,
            recipient_address='dest',
            message_body='unprocessed',
            signer='user1'
        )

        # We haven't called process yet
        self.assertFalse(self.mailbox.delivered(message_id=msg_id))
        self.assertEqual(self.mailbox.processor(message_id=msg_id), None)

    def test_set_default_ism(self):
        """
        Tests that only the owner can setDefaultIsm.
        """
        # set default ISM as sys
        self.mailbox.setDefaultIsm(module='newIsm', signer='sys')
        self.assertEqual(self.mailbox.defaultIsm.get(), 'newIsm')

        # Non-owner attempt
        with self.assertRaises(Exception) as cm:
            self.mailbox.setDefaultIsm(module='badIsm', signer='user1')
        self.assertIn("Only the contract owner can call this method", str(cm.exception))

    def test_set_default_hook(self):
        """
        Tests that only the owner can setDefaultHook.
        """
        self.mailbox.setDefaultHook(hook='someHook', signer='sys')
        self.assertEqual(self.mailbox.defaultHook.get(), 'someHook')

        with self.assertRaises(Exception) as cm:
            self.mailbox.setDefaultHook(hook='badHook', signer='user1')
        self.assertIn("Only the contract owner can call this method", str(cm.exception))

    def test_set_required_hook(self):
        """
        Tests that only the owner can setRequiredHook.
        """
        self.mailbox.setRequiredHook(hook='reqHook', signer='sys')
        self.assertEqual(self.mailbox.requiredHook.get(), 'reqHook')

        with self.assertRaises(Exception) as cm:
            self.mailbox.setRequiredHook(hook='otherHook', signer='user1')
        self.assertIn("Only the contract owner can call this method", str(cm.exception))

    def test_cross_chain_transfer(self):
        """
        Simulates bridging tokens from domain=1 -> domain=517164068468.
        
        We'll:
          1. Give user1 some local tokens (cheat by direct balance set).
          2. user1 calls xTransfer(...) -> burns locally + dispatch.
          3. Manually call the router.process(...) to simulate the cross-chain relayer.
          4. Router calls handleRemoteMint -> user2 gets minted tokens.
        """

        # 1) Give user1 some tokens by setting the raw driver store:
        #    Because 'mint' is restricted to only the router, we bypass it for test setup.
        self.c.raw_driver.set_var(
            contract='con_interchain_token',
            variable='balances',
            sub_key='user1',
            value=500
        )
        self.assertEqual(self.interchain_token.balanceOf('user1'), 500)

        # 2) user1 calls xTransfer => burns 100 tokens => dispatch
        self.mailbox.setDispatchFee(amount=0, signer='sys')  # no fee for simplicity

        msg_id = self.interchain_token.xTransfer(
            destination_domain=517164068468,  # the router is on domain=517164068468
            recipient='user2',
            amount=100,
            signer='user1'
        )

        # After burning 100 tokens, user1 should have 400 left
        self.assertEqual(self.interchain_token.balanceOf('user1'), 400)
        # A record of "burned" tokens is at balances['BRIDGE_BURNED'] for debugging
        self.assertEqual(self.interchain_token.balanceOf('BRIDGE_BURNED'), 100)

        # 3) On the "destination chain", the router sees the event. We simulate that by
        #    calling router.process(...) in the same environment.
        #
        #    The router's `process` will do mailbox.process(...) and then call 
        #    interchain_token.handleRemoteMint(...) to mint 100 tokens for 'user2'.

        # We need the original message body. Usually it's the same string we passed
        # into mailbox.dispatch. However, 'xTransfer' built that. Let's get it from
        # the mailbox's `latestDispatchedId` or re-construct it:
        # Actually, the router doesn't ask for the "raw" message body as a separate param
        # because we pass it into `router.process(...)` directly. 
        # BUT let's fetch it from mailbox's 'latestDispatchedId' if we want to confirm.
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
