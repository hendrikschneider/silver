import datetime as dt

from django.utils import timezone
from dateutil.relativedelta import *

from silver.models import Customer


class DocumentsGenerator(object):
    def generate(self, subscription=None):
        """
        The `public` method called when one wants to generate the billing
        documents.
        """

        if not subscription:
            self._generate_all()
        else:
            self._generate_for_single_subscription_now(subscription)

    def _generate_all(self):
        """
        Generates the invoices/proformas for all the subscriptions that should
        be billed.
        """

        now = timezone.now().date()
        billing_date = dt.date(now.year, now.month, 1)
        # billing_date -> the date when the billing documents are issued.

        for customer in Customer.objects.all():
            if customer.consolidated_billing:
                self._generate_for_user_with_consolidated_billing(customer,
                                                                  billing_date)
            else:
                self._generate_for_user_without_consolidated_billing(customer,
                                                                     billing_date)

    def _generate_for_user_with_consolidated_billing(self, customer,
                                                     billing_date):
        """
        Generates the billing documents for all the subscriptions of a customer
        who uses consolidated billing.
        """

        # For each provider there will be one invoice or proforma. The cache
        # is necessary as a certain customer might have more than one
        # subscription => all the subscriptions that belong to the same
        # provider will be added on the same invoice/proforma
        # => they are "cached".
        cached_documents = {}

        # Select all the active or canceled subscriptions
        criteria = {'state__in': ['active', 'canceled']}
        for subscription in customer.subscriptions.filter(**criteria):
            if not subscription.should_be_billed(billing_date):
                continue

            provider = subscription.plan.provider
            if provider in cached_documents:
                # The BillingDocument was created beforehand, now just extract it
                # and add the new entries to the document.
                document = cached_documents[provider]
            else:
                # A BillingDocument instance does not exist for this provider
                # => create one
                document = self._create_document(provider, customer,
                                                 subscription, billing_date)
                cached_documents[provider] = document

            args = {
                'billing_date': billing_date,
                provider.flow: document,
            }
            subscription.add_total_value_to_document(**args)

            if subscription.state == 'canceled':
                subscription.end()
                subscription.save()

        for provider, document in cached_documents.iteritems():
            if provider.default_document_state == 'issued':
                document.issue()
                document.save()

    def _generate_for_user_without_consolidated_billing(self, customer,
                                                        billing_date):
        """
        Generates the billing documents for all the subscriptions of a customer
        who does not use consolidated billing.
        """

        # The user does not use consolidated_billing => add each
        # subscription on a separate document (Invoice/Proforma)
        criteria = {'state__in': ['active', 'canceled']}
        for subscription in customer.subscriptions.filter(**criteria):
            if not subscription.should_be_billed(billing_date):
                continue

            provider = subscription.plan.provider
            document = self._create_document(provider, customer,
                                             subscription, billing_date)

            args = {
                'billing_date': billing_date,
                provider.flow: document,
            }
            subscription.add_total_value_to_document(**args)

            if subscription.state == 'canceled':
                subscription.end()
                subscription.save()

            if provider.default_document_state == 'issued':
                document.issue()
                document.save()

    def _generate_for_single_subscription_now(self, subscription):
        """
        Generates the billing documents corresponding to a single subscription.
        Used when a subscription is ended with `when`=`now`
        """

        now = timezone.now().date()

        provider = subscription.plan.provider
        customer = subscription.customer

        document = self._create_document(provider, customer, subscription, now)
        args = {
            'billing_date': now,
            provider.flow: document,
        }
        subscription.add_total_value_to_document(**args)

        if subscription.state == 'canceled':
            subscription.end()
            subscription.save()

        if provider.default_document_state == 'issued':
            document.issue()
            document.save()

    def _create_document(self, provider, customer, subscription, billing_date):
        DocumentModel = provider.model_corresponding_to_default_flow

        payment_due_days = dt.timedelta(days=customer.payment_due_days)
        due_date = billing_date + payment_due_days
        document = DocumentModel.objects.create(provider=provider,
                                                customer=customer,
                                                due_date=due_date)

        return document
