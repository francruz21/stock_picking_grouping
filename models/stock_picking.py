from odoo import models, fields, api, _
from odoo.exceptions import UserError

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_combine_pickings(self):
        """
        Combina los remitos seleccionados en un nuevo remito de salida (tipo entrega)
        Solo se permite combinar remitos de tipo 'Recepción' (incoming).
        """
        pickings = self.browse(self.env.context.get('active_ids', []))

        if not pickings:
            raise UserError(_("Debe seleccionar al menos un remito para combinar."))

        # Validar que todos los remitos sean de tipo 'Recepción'
       # if not all(picking.picking_type_id.code == 'incoming' for picking in pickings):
        #    raise UserError(_("Esta acción solo está permitida para remitos de tipo Recepción."))

        # Verificar permisos
        if not self.env.user.has_group('stock.group_stock_user'):
            raise UserError(_("No tiene permisos para realizar esta acción."))

        # Obtener el tipo de operación de entrega (outgoing) para el almacén correspondiente
        outgoing_picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'outgoing'),
            ('warehouse_id', 'in', pickings.mapped('picking_type_id.warehouse_id').ids)
        ], limit=1)

        if not outgoing_picking_type:
            raise UserError(_("No se encontró un tipo de operación de entrega configurado."))

        # Validar que todas las ubicaciones destino sean iguales
        dest_locations = pickings.mapped('location_dest_id')
        if len(dest_locations) > 1:
            raise UserError(_("No se pueden combinar remitos con diferentes ubicaciones de destino (clientes diferentes)."))

        # Validar que todos los remitos pertenezcan al mismo almacén
        warehouses = pickings.mapped('location_id.warehouse_id')
        if len(warehouses) > 1:
            raise UserError(_("No se pueden combinar remitos de diferentes almacenes."))

        # Crear nuevo remito combinado
        new_picking = self.env['stock.picking'].create({
            'picking_type_id': outgoing_picking_type.id,
            'location_id': outgoing_picking_type.default_location_src_id.id,
            'location_dest_id': dest_locations.id,
            'origin': ', '.join(pickings.mapped('name')),
            'move_type': 'direct',
            'partner_id': pickings[0].partner_id.id if pickings[0].partner_id else False,
            'scheduled_date': fields.Datetime.now(),
        })

        # Agrupar movimientos por producto y unidad de medida
        product_data = {}
        for picking in pickings:
            for move in picking.move_ids:
                key = (move.product_id.id, move.product_uom.id)
                if key in product_data:
                    product_data[key]['product_uom_qty'] += move.product_uom_qty
                else:
                    product_data[key] = {
                        'product_id': move.product_id,
                        'name': move.product_id.display_name + _(' (Combinado)'),
                        'product_uom_qty': move.product_uom_qty,
                        'product_uom': move.product_uom,
                        'location_id': outgoing_picking_type.default_location_src_id.id,
                        'location_dest_id': dest_locations.id,
                        'picking_id': new_picking.id,
                    }

        # Crear los movimientos en el nuevo remito
        for vals in product_data.values():
            self.env['stock.move'].create({
                'name': vals['name'],
                'product_id': vals['product_id'].id,
                'product_uom_qty': vals['product_uom_qty'],
                'product_uom': vals['product_uom'].id,
                'location_id': vals['location_id'],
                'location_dest_id': vals['location_dest_id'],
                'picking_id': vals['picking_id'],
            })

        # Procesar automáticamente si todos los remitos estaban asignados
        if all(p.state == 'assigned' for p in pickings):
            new_picking.action_assign()
            if new_picking.state == 'assigned':
                new_picking._action_done()

        # Mostrar el nuevo remito combinado
        return {
            'name': _('Remito Combinado'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'stock.picking',
            'res_id': new_picking.id,
            'target': 'current',
            'context': self.env.context,
        }
