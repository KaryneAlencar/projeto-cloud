import unittest

from app.presentation import customer_message


class PresentationTests(unittest.TestCase):
    def test_catalog_hides_internal_fields_and_preserves_name_and_price(self):
        content = '- **Brownie** (ID: 1) - R$ 8,00 (Estoque: 19)\n- **Coxinha** (ID: 7) - R$ 9,00 (Estoque: 39)'
        self.assertEqual(customer_message(content), '- **Brownie** - R$ 8,00\n- **Coxinha** - R$ 9,00')

    def test_old_command_format(self):
        self.assertEqual(customer_message('Brownie (ID 1) · R$ 8.00 · estoque 19'), 'Brownie · R$ 8.00')

    def test_escaped_markdown_from_older_history(self):
        self.assertEqual(customer_message(r'\- \*\*Brownie\*\* (ID: 1) - R$ 8,00 (Estoque: 19)'), '- **Brownie** - R$ 8,00')

    def test_keeps_purchase_quantities_order_number_and_address(self):
        content = 'Pedido #19: 2 brownies, total R$ 16,00. Entrega na sala 512, prédio 2.'
        self.assertEqual(customer_message(content), content)


if __name__ == '__main__':
    unittest.main()
