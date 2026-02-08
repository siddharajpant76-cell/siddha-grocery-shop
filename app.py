from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from models import db, User, Customer, Product, Stock, Invoice, InvoiceItem
from werkzeug.security import generate_password_hash
from datetime import datetime
import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'  # Change in production
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///billing.db'
db.init_app(app)

with app.app_context():
    db.create_all()
    # Create default admin user if not exists
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', role='admin')
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['role'] = user.role
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

# Customer Management
@app.route('/customers', methods=['GET', 'POST'])
def customers():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        address = request.form['address']
        customer = Customer(name=name, phone=phone, address=address)
        db.session.add(customer)
        db.session.commit()
        flash('Customer added')
    customers = Customer.query.all()
    return render_template('customers.html', customers=customers)

@app.route('/customers/edit/<int:id>', methods=['GET', 'POST'])
def edit_customer(id):
    customer = Customer.query.get_or_404(id)
    if request.method == 'POST':
        customer.name = request.form['name']
        customer.phone = request.form['phone']
        customer.address = request.form['address']
        db.session.commit()
        flash('Customer updated')
        return redirect(url_for('customers'))
    return render_template('edit_customer.html', customer=customer)

@app.route('/customers/delete/<int:id>')
def delete_customer(id):
    customer = Customer.query.get_or_404(id)
    db.session.delete(customer)
    db.session.commit()
    flash('Customer deleted')
    return redirect(url_for('customers'))

# Product Management
@app.route('/products', methods=['GET', 'POST'])
def products():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name']
        category = request.form['category']
        price = float(request.form['price'])
        stock_qty = int(request.form['stock'])
        product = Product(name=name, category=category, price=price)
        db.session.add(product)
        db.session.commit()
        stock = Stock(product_id=product.id, quantity=stock_qty)
        db.session.add(stock)
        db.session.commit()
        flash('Product added')
    products = Product.query.all()
    return render_template('products.html', products=products)

@app.route('/products/edit/<int:id>', methods=['GET', 'POST'])
def edit_product(id):
    product = Product.query.get_or_404(id)
    stock = Stock.query.filter_by(product_id=id).first()
    if request.method == 'POST':
        product.name = request.form['name']
        product.category = request.form['category']
        product.price = float(request.form['price'])
        stock.quantity = int(request.form['stock'])
        db.session.commit()
        flash('Product updated')
        return redirect(url_for('products'))
    return render_template('edit_product.html', product=product, stock=stock)

@app.route('/products/delete/<int:id>')
def delete_product(id):
    product = Product.query.get_or_404(id)
    stock = Stock.query.filter_by(product_id=id).first()
    db.session.delete(stock)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted')
    return redirect(url_for('products'))

# Invoice Creation
@app.route('/invoices/create', methods=['GET', 'POST'])
def create_invoice():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    customers = Customer.query.all()
    products = Product.query.all()
    if request.method == 'POST':
        customer_id = request.form['customer_id']
        items = request.form.getlist('product_id[]')
        quantities = request.form.getlist('quantity[]')
        payment_method = request.form['payment_method']
        tax = float(request.form.get('tax', 0))
        
        subtotal = 0
        invoice = Invoice(customer_id=customer_id, payment_method=payment_method, tax=tax)
        db.session.add(invoice)
        db.session.commit()
        
        for i, product_id in enumerate(items):
            product = Product.query.get(product_id)
            qty = int(quantities[i])
            stock = Stock.query.filter_by(product_id=product_id).first()
            if stock.quantity < qty:
                flash(f'Insufficient stock for {product.name}')
                db.session.delete(invoice)
                db.session.commit()
                return redirect(url_for('create_invoice'))
            item_total = product.price * qty
            subtotal += item_total
            item = InvoiceItem(invoice_id=invoice.id, product_id=product_id, quantity=qty, price=product.price)
            db.session.add(item)
            stock.quantity -= qty
        invoice.subtotal = subtotal
        invoice.total = subtotal + tax
        invoice.invoice_number = f'INV-{invoice.id}'
        db.session.commit()
        flash('Invoice created')
        return redirect(url_for('invoices'))
    return render_template('create_invoice.html', customers=customers, products=products)

# View Invoices
@app.route('/invoices')
def invoices():
    invoices = Invoice.query.all()
    return render_template('invoices.html', invoices=invoices)

# Mark Invoice as Paid
@app.route('/invoices/pay/<int:id>')
def pay_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    invoice.status = 'Paid'
    db.session.commit()
    flash('Invoice marked as Paid')
    return redirect(url_for('invoices'))

# PDF Generation
@app.route('/invoices/pdf/<int:id>')
def invoice_pdf(id):
    invoice = Invoice.query.get_or_404(id)
    filename = f'invoice_{invoice.invoice_number}.pdf'
    filepath = os.path.join('invoices', filename)
    c = canvas.Canvas(filepath, pagesize=letter)
    c.drawString(100, 750, f'Invoice: {invoice.invoice_number}')
    c.drawString(100, 730, f'Customer: {invoice.customer.name if invoice.customer else "N/A"}')
    c.drawString(100, 710, f'Date: {invoice.date_created}')
    c.drawString(100, 690, f'Subtotal: ${invoice.subtotal}')
    c.drawString(100, 670, f'Tax: ${invoice.tax}')
    c.drawString(100, 650, f'Total: ${invoice.total}')
    c.drawString(100, 630, f'Payment Method: {invoice.payment_method}')
    c.drawString(100, 610, f'Status: {invoice.status}')
    y = 590
    for item in invoice.items:
        c.drawString(100, y, f'{item.product.name} - Qty: {item.quantity} - Price: ${item.price}')
        y -= 20
    c.save()
    return send_file(filepath, as_attachment=True)

# Reports
@app.route('/reports')
def reports():
    sales = Invoice.query.filter(Invoice.status == 'Paid').all()
    low_stock = Stock.query.filter(Stock.quantity < 10).all()
    out_of_stock = Stock.query.filter(Stock.quantity == 0).all()
    return render_template('reports.html', sales=sales, low_stock=low_stock, out_of_stock=out_of_stock)

if __name__ == '__main__':
    app.run(debug=True)