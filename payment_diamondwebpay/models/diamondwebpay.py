# -*- coding: utf-8 -*-
##############################################################################
#
#    Tech-Receptives Solutions Pvt. Ltd.
#    Copyright (C) 2004-TODAY Tech-Receptives(<http://www.tech-receptives.com>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import base64
from gi.overrides.keysyms import currency
# from aptdaemon.core import Transaction
try:
    import simplejson as json
except ImportError:
    import json
from hashlib import sha1
import hmac
import logging
import urlparse

from openerp.addons.payment.models.payment_acquirer import ValidationError
from openerp.addons.payment_diamondwebpay.controllers.main import DiamondWebPayController
from openerp.osv import osv, fields
from openerp.tools import float_round

_logger = logging.getLogger(__name__)


class AcquirerDiamondWebPay(osv.Model):
    _inherit = 'payment.acquirer'

    def _get_diamondwebpay_urls(self, cr, uid, environment, context=None):
        """ DiamondWebPay URLs

         - yhpp: hosted payment page: pay.shtml for single, select.shtml for multiple
        """
        return {
            'diamondwebpay_form_url': 'https://cipg.diamondbank.com/cipg/MerchantServices/MakePayment.aspx'
        }

    def _get_providers(self, cr, uid, context=None):
        providers = super(AcquirerDiamondWebPay, self)._get_providers(cr, uid, context=context)
        providers.append(['diamondwebpay', 'DiamondWebPay'])
        return providers

    _columns = {
        'diamondwebpay_merchant_id': fields.char('Merchant Account ID', required_if_provider='diamondwebpay'),
    }

    def diamondwebpay_form_generate_values(self, cr, uid, id, partner_values, tx_values, context=None):
        base_url = self.pool['ir.config_parameter'].get_param(cr, uid, 'web.base.url')
        acquirer = self.browse(cr, uid, id, context=context)
        diamondwebpay_tx_values = dict(tx_values)
        diamondwebpay_tx_values.update({
            'diam_merchant_id': acquirer.diamondwebpay_merchant_id,
            'diam_crr_code': tx_values.get('currency').currency_code,
            'diam_amount': '%d' % int(float_round(tx_values['amount'], 2)),
            'diam_order_id': tx_values['reference'],
            'diam_submit':'Pay',
            'diam_customer_email': partner_values['email'],
            'diam_product_name':'merchandise',
            'diam_return': '%s' % urlparse.urljoin(base_url, DiamondWebPayController._return_url),
            'diam_returncancel': '%s' % urlparse.urljoin(base_url, DiamondWebPayController._cancel_url),
            'diam_returnerror': '%s' % urlparse.urljoin(base_url, DiamondWebPayController._exception_url),
            'diam_returnreject': '%s' % urlparse.urljoin(base_url, DiamondWebPayController._reject_url),
        })
        if diamondwebpay_tx_values.get('return_url'):
            diamondwebpay_tx_values['merchantReturnData'] = json.dumps({'return_url': '%s' % diamondwebpay_tx_values.pop('return_url')})
        return partner_values, diamondwebpay_tx_values

    def diamondwebpay_get_form_action_url(self, cr, uid, id, context=None):
        acquirer = self.browse(cr, uid, id, context=context)
        return self._get_diamondwebpay_urls(cr, uid, acquirer.environment, context=context)['diamondwebpay_form_url']


class TxDiamondWebPay(osv.Model):
    _inherit = 'payment.transaction'

    _columns = {
        'diamondwebpay_psp_reference': fields.char('DiamondWebPay PSP Reference'),
    }

    # --------------------------------------------------
    # FORM RELATED METHODS
    # --------------------------------------------------

    def _diamondwebpay_form_get_tx_from_data(self, cr, uid, data, context=None):
        reference, pspReference = data.get('merchantReference'), data.get('TransactionReference')
        OrderID = data.get('OrderID')
        if not OrderID or not pspReference:
            error_msg = 'DiamondWebPay: received data with missing reference (%s) or missing TransactionReference (%s)' % (reference, pspReference)
            _logger.error(error_msg)
            raise ValidationError(error_msg)

            sale_pool = self.pool.get('sale.order')
            sale_order_id = sale_pool.search(cr, uid, [('name', '=', OrderID)])
            sale_pool.write(cr, uid, sale_order_id, {'transaction_ref': pspReference})

        # find tx -> @TDENOTE use pspReference ?
        tx_ids = self.pool['payment.transaction'].search(cr, uid, [('reference', '=', pspReference)], context=context)
        if not tx_ids or len(tx_ids) > 1:
            error_msg = 'DiamondWebPay: received data for reference %s' % (pspReference)
            if not tx_ids:
                error_msg += '; no order found'
            else:
                error_msg += '; multiple order found'
            _logger.error(error_msg)
            raise ValidationError(error_msg)
        tx = self.pool['payment.transaction'].browse(cr, uid, tx_ids[0], context=context)
# 
        return tx

    def _diamondwebpay_form_get_invalid_parameters(self, cr, uid, tx, data, context=None):
        invalid_parameters = []

        # reference at acquirer: pspReference
        if tx.acquirer_reference and data.get('TransactionReference') != tx.acquirer_reference:
            invalid_parameters.append(('TransactionReference', data.get('TransactionReference'), tx.acquirer_reference))
        return invalid_parameters

    def _diamondwebpay_form_validate(self, cr, uid, tx, data, context=None):
        transaction_ref = data.get('TransactionReference', 'PENDING')
        order_id = data.get('OrderID', 'PENDING')
        if transaction_ref == data.get('TransactionReference') and order_id == data.get('OrderID'):
            tx.write({
                'state': 'done',
                'diamondwebpay_psp_reference': data.get('TransactionReference'),
            })
            return True
        elif transaction_ref == 'PENDING' or order_id == 'PENDING':
            tx.write({
                'state': 'pending',
                'diamondwebpay_psp_reference': data.get('TransactionReference'),
            })
            return True
        else:
            error = 'DiamondWebPay: feedback error'
            _logger.info(error)
            tx.write({
                'state': 'error',
                'state_message': error
            })
            return False

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4: