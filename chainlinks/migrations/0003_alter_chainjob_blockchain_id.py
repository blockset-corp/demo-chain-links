# Generated by Django 3.2.6 on 2021-08-19 14:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chainlinks', '0002_auto_20210722_1849'),
    ]

    operations = [
        migrations.AlterField(
            model_name='chainjob',
            name='blockchain_id',
            field=models.CharField(choices=[('bitcoin-mainnet', 'Bitcoin Mainnet'), ('bitcoin-testnet', 'Bitcoin Testnet'), ('bitcoincash-mainnet', 'Bitcoin Cash Mainnet'), ('bitcoincash-testnet', 'Bitcoin Cash Testnet'), ('bitcoinsv-mainnet', 'Bitcoin SV Mainnet'), ('dogecoin-mainnet', 'Dogecoin Mainnet'), ('litecoin-mainnet', 'Litecoin Mainnet'), ('hedera-mainnet', 'Hedera Mainnet'), ('ripple-mainnet', 'Ripple Mainnet'), ('tezos-mainnet', 'Tezos Mainnet'), ('ethereum-mainnet', 'Ethereum Mainnet'), ('ethereum-ropsten', 'Ethereum Testnet')], max_length=32),
        ),
    ]
