# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import And, Eval, Not
from trytond.transaction import Transaction

__all__ = ['StockMove', 'Purchase', 'PurchaseLine']
__metaclass__ = PoolMeta


class StockMove:
    __name__ = 'stock.move'

    from_openerp = fields.Boolean('Imported from OpenERP', readonly=True)
    from_openerp_to_invoice = fields.Boolean('Imported from OpenERP',
        readonly=True)

    @property
    def invoiced_quantity(self):
        if self.from_openerp:
            if self.from_openerp_to_invoice:
                return 0.0
            return self.quantity
        return super(StockMove, self).invoiced_quantity


class Purchase:
    __name__ = 'purchase.purchase'

    from_openerp = fields.Boolean('Imported from OpenERP', readonly=True)

    @classmethod
    def __setup__(cls):
        super(Purchase, cls).__setup__()
        confirm_button = cls._buttons['confirm']
        confirm_button['invisible'] = And(confirm_button['invisible'],
            Not((Eval('state') == 'confirmed') & Eval('from_openerp')))

    def get_invoice_state(self):
        state = super(Purchase, self).get_invoice_state()
        if not self.from_openerp or state == 'exception':
            return state
        if self.moves and any(m.from_openerp_to_invoice for m in self.moves):
            return 'waiting'
        elif self.moves and all(m.from_openerp for m in self.moves):
            # all moves invoiced
            if state == 'none':
                return 'paid'
        return state

    @classmethod
    def copy(cls, purchases, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default['from_openerp'] = False
        return super(Purchase, cls).copy(purchases, default=default)


class PurchaseLine:
    __name__ = 'purchase.line'

    def get_move(self):
        move = super(PurchaseLine, self).get_move()
        if move and self.purchase.from_openerp:
            move.from_openerp = True
            if self.purchase.invoice_method == 'shipment':
                move.from_openerp_to_invoice = True
        return move

    def get_invoice_line(self, invoice_type):
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        Move = pool.get('stock.move')
        Uom = pool.get('product.uom')

        if (not self.purchase.from_openerp or
                self.purchase.invoice_method != 'shipment' or
                self.type != 'line' or
                not self.product or
                self.product.type == 'service'):
            return super(PurchaseLine, self).get_invoice_line(invoice_type)
        if not self.moves:
            return []

        with Transaction().set_user(0, set_context=True):
            invoice_line = InvoiceLine()
        invoice_line.type = self.type
        invoice_line.description = self.description
        invoice_line.note = self.note
        invoice_line.origin = self
        if (invoice_type == 'in_invoice') != (self.quantity >= 0):
            return []

        quantity = 0.0
        stock_moves = []
        for move in self.moves:
            if move.state == 'done' and move.from_openerp_to_invoice:
                quantity += Uom.compute_qty(move.uom, move.quantity,
                    self.unit)
                stock_moves.append(move)
        if quantity <= 0.0:
            return []
        invoice_line.stock_moves = stock_moves

        Move.write(stock_moves, {
                'from_openerp_to_invoice': False,
                })

        invoice_line.quantity = quantity
        invoice_line.unit = self.unit
        invoice_line.product = self.product
        invoice_line.unit_price = self.unit_price
        invoice_line.taxes = self.taxes
        invoice_line.invoice_type = invoice_type
        invoice_line.account = self.product.account_expense_used
        if not invoice_line.account:
            self.raise_user_error('missing_account_expense', {
                    'product': invoice_line.product.rec_name,
                    'purchase': self.purchase.rec_name,
                    })
        return [invoice_line]
