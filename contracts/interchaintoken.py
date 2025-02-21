# ------------------------------------------------------------------------------
# EVENTS
# ------------------------------------------------------------------------------

MintEvent = LogEvent(
    event="Mint",
    params={
        "to": {"type": str},
        "amount": {"type": float}
    }
)

BurnEvent = LogEvent(
    event="Burn",
    params={
        "from": {"type": str},
        "amount": {"type": float}
    }
)

RemoteTransferEvent = LogEvent(
    event="RemoteTransfer",
    params={
        "origin_domain": {"type": int},
        "destination_domain": {"type": int},
        "sender": {"type": str},
        "recipient": {"type": str},
        "amount": {"type": float},
        "message_id": {"type": str}
    }
)

ReceiveRemoteTransferEvent = LogEvent(
    event="ReceiveRemoteTransfer",
    params={
        "sender": {"type": str},
        "amount": {"type": float}
    }
)

# ------------------------------------------------------------------------------
# STATE
# ------------------------------------------------------------------------------

balances = Hash(default_value=0)

# Owner or ADMIN role for the token
owner = Variable()

# This contract's local domain (e.g., 517164068468 for Xian)
localDomain = Variable()

# The name (or address) of the 'InterchainTokenRouter' on this chain
routerName = Variable()

# Mailbox contract for cross-chain messaging
mailbox = Variable()

# Interchain Router contract for cross-chain token transfers
interchainRouter = Variable()

@construct
def seed(domain: int, router: str, mailbox_contract: str, interchain_router_contract: str):
    """
    domain: Local domain ID for this chain
    router: Name (or address) of the InterchainTokenRouter on this chain
    """
    owner.set(ctx.caller)
    localDomain.set(domain)
    routerName.set(router)
    mailbox.set(mailbox_contract)
    interchainRouter.set(interchain_router_contract)

# ------------------------------------------------------------------------------
# MODIFIERS / HELPERS
# ------------------------------------------------------------------------------

def only_owner():
    if ctx.caller != owner.get():
        raise Exception("Only the owner can call this function.")

def only_router():
    """
    In a Hyperlane-like system, only the router on this chain
    should call cross-chain mint, to ensure security & message authenticity.
    """
    if ctx.caller != routerName.get():
        raise Exception("Only the configured router can call this function.")

# ------------------------------------------------------------------------------
# ERC20-LIKE METHODS
# ------------------------------------------------------------------------------

@export
def balanceOf(account: str) -> float:
    return balances[account]

@export
def transfer(amount: float, to: str):
    assert amount > 0, 'Cannot send negative balances!'

    sender = ctx.caller

    assert balances[sender] >= amount, 'Not enough coins to send!'

    balances[sender] -= amount
    balances[to] += amount

@export
def allowance(owner: str, spender: str):
    return balances[owner, spender]

@export
def approve(amount: float, to: str):
    assert amount > 0, 'Cannot send negative balances!'

    sender = ctx.caller
    balances[sender, to] += amount
    return balances[sender, to]

@export
def transfer_from(amount: float, to: str, main_account: str):
    assert amount > 0, 'Cannot send negative balances!'

    sender = ctx.caller

    assert balances[main_account, sender] >= amount, 'Not enough coins approved to send! You have {} and are trying to spend {}'\
        .format(balances[main_account, sender], amount)
    assert balances[main_account] >= amount, 'Not enough coins to send!'

    balances[main_account, sender] -= amount
    balances[main_account] -= amount

    balances[to] += amount


@export
def mint(to: str, amount: float):
    """
    Called internally or by the router (after cross-chain bridging).
    """
    only_router()  # Usually only the router can mint cross-chain
    balances[to] += amount
    MintEvent({"to": to, "amount": amount})

@export
def burn(amount: float):
    """
    Burn tokens on the origin chain before bridging out.
    The user calls burn directly or via a helper function.
    """
    if balances[ctx.caller] < amount:
        raise Exception("Insufficient balance to burn.")
    balances[ctx.caller] -= amount
    balances['BRIDGE_BURNED'] += amount
    BurnEvent({"from": ctx.caller, "amount": amount})

# ------------------------------------------------------------------------------
# CROSS-CHAIN FUNCTIONS
# ------------------------------------------------------------------------------

@export
def xTransfer(destination_domain: int, recipient: str, amount: float):
    """
    Burns tokens locally and dispatches a cross-chain message to the router on the
    destination chain. The router will then call 'mint' on that chain's InterchainToken.
    """
    # 1. Burn the tokens locally
    burn(amount)

    # 2. Construct a message with the bridging details
    message_body = f"{ctx.caller}|{recipient}|{amount}|{localDomain.get()}"

    mailbox = importlib.import_module(mailbox.get())

    # 3. Dispatch message to the "InterchainTokenRouter" on the remote domain
    msg_id = mailbox.dispatch(
        destination_domain=destination_domain,
        recipient_address=interchainRouter.get(),
        message_body=message_body
    )

    RemoteTransferEvent({
        "origin_domain": localDomain.get(),
        "destination_domain": destination_domain,
        "sender": ctx.caller,
        "recipient": recipient,
        "amount": amount,
        "message_id": msg_id
    })
    return msg_id

@export
def handleRemoteMint(sender: str, recipient: str, amount: float):
    """
    Called by the router on this chain after verifying and decoding
    the cross-chain message. Mints tokens locally.
    """
    only_router()
    balances[recipient] += amount

    ReceiveRemoteTransferEvent({
        "sender": sender,
        "amount": amount
    })
