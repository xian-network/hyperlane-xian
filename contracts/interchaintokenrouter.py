RouterMessageEvent = LogEvent(
    event="RouterMessage",
    params={
        "message_body": {"type": str},
        "sender_domain": {"type": int},
        "sender_address": {"type": str}
    }
)

# We store a mapping: domainID -> nameOfInterchainTokenOnThatDomain
# For example: 1 -> 'InterchainTokenOnEthereum'
tokensByDomain = Hash(default_value="")

# The local domain for this router's chain
localDomain = Variable()

owner = Variable()

mailbox_contract = Variable()

@construct
def seed(domain: int, mailbox_contract_name: str):
    """
    domain: The local domain ID for this router's chain
    """
    localDomain.set(domain)
    owner.set(ctx.caller)
    mailbox_contract.set(mailbox_contract_name)

def only_owner():
    assert ctx.caller == owner.get(), "Only the contract owner can call this method."

@export
def setTokenForDomain(domain_id: int, token_name: str):
    """
    Store the name (or address) of the InterchainToken contract on 'domain_id'.
    Example usage:
      router.setTokenForDomain(1, 'InterchainTokenETH')
      router.setTokenForDomain(2, 'InterchainTokenPolygon')
    """
    only_owner()
    tokensByDomain[domain_id] = token_name

@export
def getTokenForDomain(domain_id: int):
    return tokensByDomain[domain_id]

@export
def process(message_body: str, message_id: str):
    """
    The mailbox on this chain calls 'router.process(...)'
    when a cross-chain message arrives with 'recipient_address' = 'InterchainTokenRouter'.

    We parse the message_body. Format from xTransfer might be:
      sender|recipient|amount|originDomain
    Then we call 'handleRemoteMint(...)' on the local InterchainToken to finalize.
    """

    mailbox = importlib.import_module(mailbox_contract.get())

    # Mark the message as delivered in mailbox
    mailbox.process(metadata=message_body, message_id=message_id)

    # Parse out the bridging details
    # Format: sender|recipient|amount|originDomain
    parts = message_body.split("|")
    assert len(parts) == 4, "Invalid message format."
    sender = parts[0]
    recipient = parts[1]
    amount_str = parts[2]
    origin_domain_str = parts[3]

    amount = decimal(amount_str)
    origin_domain = int(origin_domain_str)

    RouterMessageEvent({
        "message_body": message_body,
        "sender_domain": origin_domain,
        "sender_address": sender
    })

    # Now we call the local InterchainToken to mint tokens
    # 1. We look up the local InterchainToken name for this domain
    local_token_name = tokensByDomain[localDomain.get()]
    assert local_token_name, "No InterchainToken configured for this domain."

    interchain_token = importlib.import_module(local_token_name)

    # 3. Forward the mint call
    interchain_token.handleRemoteMint(sender, recipient, amount)

    # Done! The local InterchainToken has minted tokens to the recipient.
