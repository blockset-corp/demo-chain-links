# Generated by Django 3.2.6 on 2021-08-05 23:45

import datetime
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
from django.utils.timezone import utc


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='ChainBlock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('scheduled', models.DateTimeField()),
                ('block_height', models.BigIntegerField()),
                ('completed', models.DateTimeField(default=datetime.datetime(1970, 1, 1, 0, 0, tzinfo=utc))),
                ('status', models.CharField(choices=[('pd', 'Pending'), ('gd', 'Good'), ('bd', 'Bad'), ('fl', 'Failure')], max_length=2)),
            ],
        ),
        migrations.CreateModel(
            name='ChainJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('enabled', models.BooleanField()),
                ('service_id', models.CharField(choices=[('blockset', 'Blockset'), ('infura', 'Infura')], max_length=32)),
                ('blockchain_id', models.CharField(choices=[('bitcoin-mainnet', 'Bitcoin Mainnet'), ('bitcoin-testnet', 'Bitcoin Testnet'), ('bitcoincash-mainnet', 'Bitcoin Cash Mainnet'), ('bitcoincash-testnet', 'Bitcoin Cash Testnet'), ('bitcoinsv-mainnet', 'Bitcoin SV Mainnet'), ('dogecoin-mainnet', 'Dogecon Mainnet'), ('litecoin-mainnet', 'Litecoin Mainnet'), ('hedera-mainnet', 'Hedera Mainnet'), ('ripple-mainnet', 'Ripple Mainnet'), ('tezos-mainnet', 'Tezos Mainnet'), ('ethereum-mainnet', 'Ethereum Mainnet'), ('ethereum-ropsten', 'Ethereum Testnet')], max_length=32)),
                ('start_height', models.BigIntegerField(validators=[django.core.validators.MinValueValidator(0)])),
                ('end_height', models.BigIntegerField(default=9223372036854775807, validators=[django.core.validators.MinValueValidator(0)])),
                ('inflight_max', models.IntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ('finality_depth', models.IntegerField(validators=[django.core.validators.MinValueValidator(1)])),
            ],
        ),
        migrations.CreateModel(
            name='ChainBlockFetch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('canonical_http_status', models.IntegerField()),
                ('canonical_block_hash', models.CharField(max_length=1024)),
                ('canonical_prev_hash', models.CharField(max_length=1024)),
                ('canonical_txn_count', models.IntegerField()),
                ('service_http_status', models.IntegerField()),
                ('service_block_hash', models.CharField(max_length=1024)),
                ('service_prev_hash', models.CharField(max_length=1024)),
                ('service_txn_count', models.IntegerField()),
                ('block', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='chainlinks.chainblock')),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='chainlinks.chainjob')),
            ],
        ),
        migrations.AddField(
            model_name='chainblock',
            name='fetch',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='chainlinks.chainblockfetch'),
        ),
        migrations.AddField(
            model_name='chainblock',
            name='job',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='chainlinks.chainjob'),
        ),
        migrations.AddIndex(
            model_name='chainblock',
            index=models.Index(fields=['status'], name='cb_status'),
        ),
        migrations.AddIndex(
            model_name='chainblock',
            index=models.Index(fields=['-block_height'], name='cb_block_height'),
        ),
        migrations.AlterUniqueTogether(
            name='chainblock',
            unique_together={('job', 'block_height')},
        ),
    ]
