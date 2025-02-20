import currency  # If you want to charge fees in 'currency', for example

################################################################################
# EVENTS
################################################################################

DispatchEvent = LogEvent(
    event="Dispatch",
    params={
        "sender": {"type": str},
        "origin_domain": {"type": int, "idx": True},
        "destination_domain": {"type": int, "idx": True},
        "recipient": {"type": str},
        "message_id": {"type": str, "idx": True},
        "nonce": {"type": int}
    }
)

ProcessEvent = LogEvent(
    event="Process",
    params={
        "message_id": {"type": str, "idx": True},
        "processor": {"type": str, "idx": True},
        "block_number": {"type": int},
    }
)

DefaultIsmEvent = LogEvent(
    event="DefaultIsmSet",
    params={
        "module": {"type": str, "idx": True}
    }
)

DefaultHookEvent = LogEvent(
    event="DefaultHookSet",
    params={
        "hook": {"type": str, "idx": True}
    }
)

RequiredHookEvent = LogEvent(
    event="RequiredHookSet",
    params={
        "hook": {"type": str, "idx": True}
    }
)

################################################################################
# STATE
################################################################################

VERSION = 1

localDomain = Variable()
nonce = Variable()  # uint32-like
latestDispatchedId = Variable()  # tracks last message id
defaultIsm = Variable()
defaultHook = Variable()
requiredHook = Variable()
owner = Variable()

# deliveries: Hash mapping message ID -> {processor: str, blockNumber: int}
deliveries = Hash(default_value={"processor": None, "blockNumber": 0})

dispatchFee = Variable()

################################################################################
# CONSTRUCTOR
################################################################################

@construct
def seed():

    localDomain.set(517164068468)
    nonce.set(0)
    latestDispatchedId.set(0)

    defaultIsm.set("defaultIsm")
    defaultHook.set("defaultHook")
    requiredHook.set("requiredHook")
    dispatchFee.set(0)

    owner.set(ctx.caller)

################################################################################
# INTERNAL HELPERS
################################################################################

def only_owner():
    if ctx.caller != owner.get():
        raise Exception("Only the contract owner can call this method.")

def build_message(origin_domain: int,
                   sender: str,
                   destination_domain: int,
                   recipient: str,
                   body: str):
    """
    Approximate the "message" concept. 
    """
    return {
        "version": VERSION,
        "nonce": nonce.get(),
        "originDomain": origin_domain,
        "sender": sender,
        "destinationDomain": destination_domain,
        "recipient": recipient,
        "body": body
    }

def generate_message_id(message: dict):
    """
    Pseudo-hash to generate unique message ID from message fields.
    """
    m_str = f"{message['version']}-{message['nonce']}-{message['originDomain']}-{message['sender']}-{message['destinationDomain']}-{message['recipient']}-{message['body']}"
    m_str = m_str.encode('utf-8').hex()
    return hashlib.sha256(m_str)

################################################################################
# PUBLIC FUNCTIONS
################################################################################

@export
def setDefaultIsm(module: str):
    """
    Equivalent to 'setDefaultIsm' in the Solidity contract. Owner only.
    """
    only_owner()
    defaultIsm.set(module)
    DefaultIsmEvent({"module": module})


@export
def setDefaultHook(hook: str):
    """
    Equivalent to 'setDefaultHook' in the Solidity contract. Owner only.
    """
    only_owner()
    defaultHook.set(hook)
    DefaultHookEvent({"hook": hook})


@export
def setRequiredHook(hook: str):
    """
    Equivalent to 'setRequiredHook' in the Solidity contract. Owner only.
    """
    only_owner()
    requiredHook.set(hook)
    RequiredHookEvent({"hook": hook})


@export
def dispatch(destination_domain: int,
             recipient_address: str,
             message_body: str):
    """
    Dispatch a message to another domain.
    """
    if dispatchFee.get() > 0:
        currency.transfer_from(amount=dispatchFee.get(), to=owner.get(), main_account=ctx.caller)

    origin = localDomain.get()
    current_nonce = nonce.get()

    # Build + ID the message
    message = build_message(origin, ctx.caller, destination_domain, recipient_address, message_body)
    msg_id = generate_message_id(message)

    nonce.set(current_nonce + 1)
    latestDispatchedId.set(msg_id)

    DispatchEvent({
        "sender": ctx.caller,
        "origin_domain": origin,
        "destination_domain": destination_domain,
        "recipient": recipient_address,
        "message_id": msg_id,
        "nonce": current_nonce
    })

    return msg_id


@export
def process(metadata: str,  
            message_id: str):
    """
    Process a message. This is the equivalent of 'process' in the Solidity contract.
    """
    delivered_info = deliveries[message_id]
    if delivered_info["blockNumber"] > 0:
        raise Exception("Mailbox: already delivered")

    deliveries[message_id] = {
        "processor": ctx.caller,
        "blockNumber": block_num
    }

    ProcessEvent({
        "message_id": message_id,
        "processor": ctx.caller,
        "block_number": deliveries[message_id]["blockNumber"]
    })


@export
def delivered(message_id: str):
    """
    Check if the message has been marked as delivered.
    """
    return deliveries[message_id]["blockNumber"] > 0


@export
def processor(message_id: str):
    """
    Return the account that processed the given message.
    """
    return deliveries[message_id]["processor"]


@export
def processedAt(message_id: str):
    """
    Return the block number at which the message was processed.
    """
    return deliveries[message_id]["blockNumber"]

@export
def getDispatchFee():
    """
    Get the dispatch fee.
    """
    return dispatchFee.get()

@export
def setDispatchFee(amount: float):
    """
    Set the dispatch fee. Owner only.
    """
    only_owner()
    dispatchFee.set(amount)