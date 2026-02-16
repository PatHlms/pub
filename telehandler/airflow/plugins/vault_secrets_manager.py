import hvac

class VaultSecretsManager:
    def __init__(self, url, token):
        self.client = hvac.Client(url=url, token=token)

    def get_secret(self, path, key):
        secret = self.client.secrets.kv.read_secret_version(path=path)
        return secret['data']['data'].get(key)

    def set_secret(self, path, key, value):
        self.client.secrets.kv.create_or_update_secret(path=path, secret={key: value})

    def delete_secret(self, path):
        self.client.secrets.kv.delete_metadata_and_all_versions(path=path)

# Example usage:
# vault = VaultSecretsManager(url='http://127.0.0.1:8200', token='YOUR_VAULT_TOKEN')
# vault.set_secret('my-secret-path', 'password', 'supersecret')
# password = vault.get_secret('my-secret-path', 'password')
# vault.delete_secret('my-secret-path')
