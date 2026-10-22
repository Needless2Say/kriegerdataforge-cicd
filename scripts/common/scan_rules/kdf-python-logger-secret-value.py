# The KDF rule's own test cases, in Opengrep's test form, run by make scan-fixtures (D-084). Each line the rule must
# flag sits under a ruleid comment and each it must leave alone under an ok comment. Every name and value is made up.
import logging

logger = logging.getLogger(__name__)


class Client:
    def __init__(self):
        self.log = logging.getLogger("client")

    def send(self, headers, access_token, user_id):
        # ruleid: kdf-python-logger-secret-value
        self.log.debug("sending with %s", headers)
        # ruleid: kdf-python-logger-secret-value
        self.log.info(f"the token is {access_token}")
        # ok: kdf-python-logger-secret-value
        self.log.info("sent for user %s", user_id)


def sign_in(username, password, api_key, auth_code, session_cookie, credentials, client_secret, error):
    # ruleid: kdf-python-logger-secret-value
    logger.info("sign in for %s with %s", username, password)
    # ruleid: kdf-python-logger-secret-value
    logger.debug("the key {}".format(api_key))
    # ruleid: kdf-python-logger-secret-value
    logger.warning("exchanging a code", extra={"grant": auth_code})
    # ruleid: kdf-python-logger-secret-value
    logging.error("cookie %s", session_cookie)
    # ruleid: kdf-python-logger-secret-value
    logger.info("credentials %r", credentials)
    # ruleid: kdf-python-logger-secret-value
    logger.exception("secret %s", client_secret)
    # ok: kdf-python-logger-secret-value
    logger.info("Password changed for user: %s", username)
    # ok: kdf-python-logger-secret-value
    logger.error("Could not hash the password: %s", type(error).__name__)
    # ok: kdf-python-logger-secret-value
    logger.warning("Sign out, the token was not revoked (%s)", error.__class__.__name__)
    # ok: kdf-python-logger-secret-value
    logger.info("A password reset was asked for user %d", 7)


def answer(response, authorization, monkey):
    # ruleid: kdf-python-logger-secret-value
    logger.debug("auth %s", authorization)
    # ok: kdf-python-logger-secret-value
    logger.info("status %s", response.status_code)
    # ok: kdf-python-logger-secret-value
    logger.info("animal %s", monkey)
