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

from apt.package import Record

try:
    import simplejson as json
except ImportError:
    import json
import logging
import pprint
import urllib2
import werkzeug
from suds.client import Client

from openerp import http, SUPERUSER_ID
from openerp.http import request

_logger = logging.getLogger(__name__)


class DiamondWebPayController(http.Controller):
    _return_url = '/payment/diamondwebpay/return'
    _cancel_url = '/payment/diamondwebpay/cancel'
    _exception_url = '/payment/diamondwebpay/error'
    _reject_url = '/payment/diamondwebpay/reject'

    def diamondwebpay_return_url(self, **post):
        return_url = post.pop('return_url', '')
        if not return_url:
            custom = json.loads(post.pop('custom', False) or '{}')
            return_url = custom.get('return_url', '/')
        return return_url

    def diamondwebpay_PaymentOrder(self, merchantID, OrderId):
        validate_url = "https://cipg.diamondbank.com/CIPG/WebService/TransactionStatusCheck.svc?wsdl"
        iwl = Client(validate_url)
        paymentResult = iwl.service.GetTransactionDetails(OrderId, merchantID)
        return paymentResult

    def diamondwebpay_validate_data(self, **post):
        values = {}
        res = False
        new_post = dict(post, cmd='_notify-validate')
        cr, uid, context = request.cr, request.uid, request.context
        reference = post.get('OrderID')
        tx = None
        if reference:
            tx_ids = request.registry['payment.transaction'].search(cr, uid, [('reference', '=', reference)], context=context)
            if tx_ids:
                tx = request.registry['payment.transaction'].browse(cr, uid, tx_ids[0], context=context)
        diamondwebpay_urls = request.registry['payment.acquirer']._get_diamondwebpay_urls(cr, uid, tx and tx.acquirer_id and tx.acquirer_id.environment or 'prod', context=context)
        search_merchantID = request.registry['payment.acquirer'].search(cr, uid, [('provider', '=', "diamondwebpay")], context=context)
        merchantID = request.registry['payment.acquirer'].browse(cr, uid, search_merchantID, context=context).diamondwebpay_merchant_id
        status = self.diamondwebpay_PaymentOrder(merchantID, post.get('OrderID'))
        if not status:
            _logger.warning('Diamondwebpay: answered UNSUCCESSFUL on data verification')
        payment_result = status.split('&')
        order_id = request.registry['sale.order'].search(cr, SUPERUSER_ID, [('name', '=', post.get('OrderID'))], context=context)
        order_record = request.registry['sale.order'].browse(cr, SUPERUSER_ID, order_id, context=context)
        currency_id = request.registry['res.currency'].search(cr, SUPERUSER_ID, [('name', '=', 'NGN')], context=context)

        try:
            values.update({
                'date_create': order_record.date_order,
                'date_validate': payment_result[7],
                'acquirer_id': search_merchantID and search_merchantID[0] or False,
                'type': 'form',
                'state': 'done',
                # payment
                'amount': order_record.amount_total,
                'currency_id': (currency_id and currency_id[0] or False),
                'reference': post.get('TransactionReference'),
                'partner_id': order_record.partner_id.id,
                'partner_name': order_record.partner_id.name or False,
                'partner_lang': order_record.partner_id.lang or False,
                'partner_email': order_record.partner_id.email or False,
                'partner_zip': order_record.partner_id.zip or False,
                'partner_address': order_record.partner_id.street or False,
                'partner_city': order_record.partner_id.city or False,
                'partner_country_id': order_record.partner_id.country_id.id or False,
                'partner_phone': order_record.partner_id.phone or False,
            })
            tx_id = request.registry['payment.transaction'].create(cr, SUPERUSER_ID, values, context=context)
        except Exception, e:
            raise
        cr.commit()
        if payment_result[4] == 'Successful':
            _logger.info('Diamondwebpay: validated data')
            res = request.registry['payment.transaction'].form_feedback(cr, SUPERUSER_ID, post, 'diamondwebpay', context=context)
        elif payment_result[4] == 'Failed':
            _logger.warning('Diamondwebpay: answered INVALID on data verification')
        else:
            _logger.warning('Diamondwebpay: unrecognized diamondwebpay answer, received %s instead of VERIFIED or INVALID' % resp.text)
        return res

    @http.route('/payment/diamondwebpay/return', type='http', auth='none', methods=['GET'])
    def diamondwebpay_return(self, **post):
        _logger.info('Beginning Diamondwebpay IPN form_feedback with post data %s', pprint.pformat(post))  # debug
        self.diamondwebpay_validate_data(**post)
        return_url = self.diamondwebpay_return_url(**post)
        return werkzeug.utils.redirect(return_url)

    @http.route('/payment/diamondwebpay/cancel', type='http', auth="none")
    def diamondwebpay_cancel(self, **post):
        _logger.info('Beginning Diamondwebpay cancel with post data %s', pprint.pformat(post))  # debug
        return_url = self.diamondwebpay_return_url(**post)
        return werkzeug.utils.redirect(return_url)

    @http.route('/payment/diamondwebpay/error', type='http', auth="none")
    def diamondwebpay_error(self, **post):
        _logger.info('Beginning Diamondwebpay form_feedback with post data %s', pprint.pformat(post))  # debug
        return_url = self.diamondwebpay_return_url(**post)
        return werkzeug.utils.redirect(return_url)

    @http.route('/payment/diamondwebpay/reject', type='http', auth="none")
    def diamondwebpay_reject(self, **post):
        _logger.info('Beginning Diamondwebpay reject with post data %s', pprint.pformat(post))  # debug
        return_url = self.diamondwebpay_return_url(**post)
        return werkzeug.utils.redirect(return_url)

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4: