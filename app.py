from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
import datetime
import json
import pytz
import os 

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev")  # Cambiar a config segura en producción

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client["pos_system"]

productos_col = db["productos"]
pedidos_col = db["pedidos"]

@app.route("/menu")
def menu():
    return render_template("menu.html")


@app.route("/")
def index():
    return redirect(url_for("menu"))


@app.route("/productos")
def listar_productos():
    productos = list(productos_col.find())
    return render_template("productos.html", productos=productos)

@app.route("/productos/nuevo", methods=["GET", "POST"])
def nuevo_producto():
    categorias = list(db.categorias.find())
    if request.method == "POST":
        nombre = request.form.get("nombre")
        categoria = request.form.get("categoria")
        codigo = request.form.get("codigo") or None
        imagen_url = request.form.get("imagen_url") or None

        
        precio = float(request.form.get("precio", 0))
        precios_por_tamano = {}  # <-- en vez de None, siempre guardamos un dict vacío
        stock = int(request.form.get("stock", 0)) if categoria == "bebida" else None


        producto = {
            "nombre": nombre,
            "categoria": categoria,
            "precio": precio,
            "precios_por_tamano": precios_por_tamano,
            "stock": stock,
            "codigo": codigo,
            "imagen_url": imagen_url,
            "historial_precios": []
        }
        productos_col.insert_one(producto)
        flash("Producto agregado exitosamente")
        return redirect(url_for("listar_productos"))

    return render_template("nuevo_producto.html", categorias=categorias)



@app.route("/categorias/nuevo", methods=["GET", "POST"])
def nueva_categoria():
    if request.method == "POST":
        nombre = request.form.get("nombre").strip().lower()
        if nombre:
            # Verificar que no exista ya
            existente = db.categorias.find_one({"nombre": nombre})
            if existente:
                flash("La categoría ya existe.", "error")
            else:
                db.categorias.insert_one({"nombre": nombre})
                flash("Categoría agregada correctamente.", "success")
                return redirect(url_for("nuevo_producto"))
        else:
            flash("Debe ingresar un nombre para la categoría.", "error")

    return render_template("nueva_categoria.html")



@app.route("/productos/editar/<id>", methods=["GET", "POST"])
def editar_producto(id):
    producto = productos_col.find_one({"_id": ObjectId(id)})
    if not producto:
        flash("Producto no encontrado")
        return redirect(url_for("listar_productos"))
    
    if request.method == "POST":
        nombre = request.form.get("nombre")
        categoria = request.form.get("categoria")
        codigo = request.form.get("codigo") or None
        imagen_url = request.form.get("imagen_url") or None
        motivo_cambio = request.form.get("motivo_cambio", "").strip()
        precio_nuevo = float(request.form.get("precio", 0))

        cambios = {
            "nombre": nombre,
            "categoria": categoria,
            "codigo": codigo,
            "imagen_url": imagen_url
        }

        # Si es bebida, guardamos stock, si no, lo dejamos en None
        cambios["stock"] = int(request.form.get("stock", 0)) if categoria == "bebida" else None
        
        # Sin opción "camotillo", siempre dejamos un dict vacío
        cambios["precios_por_tamano"] = {}

        # Guardar historial si el precio cambió
        precio_anterior = producto.get("precio", 0)
        if precio_nuevo != precio_anterior:
            historial = producto.get("historial_precios", [])
            historial.append({
                "fecha": datetime.datetime.utcnow(),
                "precio_anterior": precio_anterior,
                "precio_nuevo": precio_nuevo,
                "motivo": motivo_cambio or "Sin motivo"
            })
            cambios["precio"] = precio_nuevo
            cambios["historial_precios"] = historial
        else:
            cambios["precio"] = precio_anterior

        # Actualizamos en la base
        productos_col.update_one({"_id": ObjectId(id)}, {"$set": cambios})
        flash("Producto actualizado")
        return redirect(url_for("listar_productos"))

    return render_template("editar_producto.html", producto=producto)


@app.route('/pos')
def pos_panel():
    pedidos_activos = list(pedidos_col.find({"estado": "Pendiente"}))
    pedidos_pagados = list(pedidos_col.find({"estado": "Pagado"}))

    # Aquí debes convertir _id a string
    for pedido in pedidos_activos + pedidos_pagados:
        pedido["_id"] = str(pedido["_id"])

    return render_template("pos_panel.html", pedidos_activos=pedidos_activos, pedidos_pagados=pedidos_pagados)


def convertir_objectid_a_str(lista_docs):
    for doc in lista_docs:
        doc["_id"] = str(doc["_id"])
    return lista_docs


@app.route("/pos/nuevo", methods=["GET", "POST"])
def pos_nuevo_pedido():
    categorias = convertir_objectid_a_str(list(db.categorias.find()))
    productos = convertir_objectid_a_str(list(productos_col.find()))

    if request.method == "POST":
        cliente = (request.form.get("cliente") or "").strip() or "Cliente sin nombre"
        descripcion = (request.form.get("descripcion") or "").strip()
        productos_pedido = json.loads(request.form.get("productos_pedido") or "[]")

        if not productos_pedido:
            flash("Debe agregar al menos un producto al pedido.", "error")
            return redirect(url_for("pos_nuevo_pedido"))

        total = 0
        detalles = []
        for p in productos_pedido:
            prod = productos_col.find_one({"_id": ObjectId(p.get("producto_id"))})
            if not prod:
                continue

            cantidad = int(p.get("cantidad", 1))
            precio_unitario = prod.get("precio", 0) or 0

            total += precio_unitario * cantidad
            detalles.append({
                "producto_id": prod["_id"],
                "nombre": prod.get("nombre", "Producto sin nombre"),
                "cantidad": cantidad,
                "precio_unitario": precio_unitario
            })

            # ✅ Actualizar stock si es bebida
            if prod.get("categoria") == "bebida" and prod.get("stock") is not None:
                nuevo_stock = max(prod["stock"] - cantidad, 0)
                productos_col.update_one({"_id": prod["_id"]}, {"$set": {"stock": nuevo_stock}})

        pedido = {
            "cliente": cliente,
            "descripcion": descripcion,
            "productos": detalles,
            "total": total,
            "estado": "Pendiente",
            "fecha": datetime.datetime.utcnow()
        }
        pedidos_col.insert_one(pedido)
        flash("Pedido creado correctamente", "success")
        return redirect(url_for("pos_panel"))

    return render_template("nuevo_pedido.html", categorias=categorias, productos=productos)




@app.route('/pos/pedido/editar/<pedido_id>', methods=['GET', 'POST'])
def editar_pedido(pedido_id):
    pedido = pedidos_col.find_one({"_id": ObjectId(pedido_id)})
    if not pedido:
        flash("Pedido no encontrado", "error")
        return redirect(url_for('pos_panel'))

    categorias = list(db.categorias.find())
    productos = list(productos_col.find())

    if request.method == 'POST':
        cliente = request.form.get('cliente', '').strip() or "Cliente sin nombre"
        descripcion = request.form.get('descripcion', '').strip()
        productos_pedido = json.loads(request.form.get('productos_pedido') or "[]")

        if not productos_pedido:
            flash("Debe agregar al menos un producto al pedido.", "error")
            return redirect(url_for('editar_pedido', pedido_id=pedido_id))

        # --- Ajustar stock: primero revertimos cantidades del pedido anterior ---
        for p in pedido["productos"]:
            prod_db = productos_col.find_one({"_id": ObjectId(p["producto_id"])})
            if prod_db and prod_db.get("categoria", "").lower() == "bebida":
                stock_actual = prod_db.get("stock", 0)
                productos_col.update_one(
                    {"_id": prod_db["_id"]},
                    {"$set": {"stock": stock_actual + p["cantidad"]}}
                )

        # --- Calcular total y preparar detalles ---
        total = 0
        detalles = []
        for p in productos_pedido:
            prod = productos_col.find_one({"_id": ObjectId(p["producto_id"])})
            if not prod:
                continue
            cantidad = int(p.get("cantidad", 1))
            precio_unitario = prod.get("precio", 0)

            # Ajustar stock para bebidas
            if prod.get("categoria", "").lower() == "bebida":
                stock_actual = prod.get("stock", 0)
                if cantidad > stock_actual:
                    flash(f"No hay suficiente stock de {prod['nombre']}. Stock actual: {stock_actual}", "error")
                    return redirect(url_for('editar_pedido', pedido_id=pedido_id))
                productos_col.update_one(
                    {"_id": prod["_id"]},
                    {"$set": {"stock": stock_actual - cantidad}}
                )

            total += precio_unitario * cantidad
            detalles.append({
                "producto_id": prod["_id"],
                "nombre": prod["nombre"],
                "cantidad": cantidad,
                "precio_unitario": precio_unitario
            })

        cambios = {
            "cliente": cliente,
            "descripcion": descripcion,
            "productos": detalles,
            "total": total,
            "fecha_actualizacion": datetime.datetime.utcnow()
        }

        pedidos_col.update_one({"_id": ObjectId(pedido_id)}, {"$set": cambios})
        flash("Pedido actualizado correctamente", "success")
        return redirect(url_for('pos_panel'))

    # Convertir ObjectId a str para JS
    for p in pedido["productos"]:
        p["producto_id"] = str(p["producto_id"])
    pedido["_id"] = str(pedido["_id"])

    return render_template("editar_pedido.html", pedido=pedido, categorias=categorias, productos=productos)





@app.route('/productos/eliminar/<id>', methods=['POST'])
def eliminar_producto(id):
    resultado = productos_col.delete_one({"_id": ObjectId(id)})
    if resultado.deleted_count == 1:
        flash("Producto eliminado correctamente.", "success")
    else:
        flash("No se encontró el producto para eliminar.", "error")
    return redirect(url_for('listar_productos'))


@app.route('/pos/pedido/<pedido_id>/eliminar', methods=['POST'])
def eliminar_pedido(pedido_id):
    result = pedidos_col.delete_one({"_id": ObjectId(pedido_id)})
    if result.deleted_count == 1:
        flash("Pedido eliminado correctamente", "success")
    else:
        flash("No se encontró el pedido para eliminar", "error")
    return redirect(url_for('pos_panel'))



@app.route("/pos/pedido/nuevo", methods=["POST"])
def pos_pedido_nuevo_api():
    data = request.json
    cliente = data.get("cliente", "Cliente sin nombre")
    empleado = data.get("empleado", "Desconocido")
    producto_id = data.get("producto_id")
    cantidad = int(data.get("cantidad", 1))

    if not producto_id:
        return jsonify({"error": "Producto requerido"}), 400

    producto = productos_col.find_one({"_id": ObjectId(producto_id)})
    if not producto:
        return jsonify({"error": "Producto no encontrado"}), 404

    precio_unitario = producto["precio"]

    pedido = {
        "cliente": cliente,
        "empleado": empleado,
        "productos": [{
            "producto_id": producto["_id"],
            "nombre": producto["nombre"],
            "cantidad": cantidad,
            "precio_unitario": precio_unitario,
        }],
        "total": precio_unitario * cantidad,
        "estado": "Pendiente",
        "fecha": datetime.datetime.utcnow()
    }
    result = pedidos_col.insert_one(pedido)
    pedido["_id"] = result.inserted_id

    # Convertir ObjectId a str en todos los campos
    pedido["_id"] = str(pedido["_id"])
    for p in pedido["productos"]:
        p["producto_id"] = str(p["producto_id"])

    return jsonify({"pedido": pedido})



@app.route('/pos/pedido/<pedido_id>/detalles_pago')
def ver_detalles_pago(pedido_id):
    pedido = pedidos_col.find_one({"_id": ObjectId(pedido_id)})
    if not pedido:
        flash("Pedido no encontrado", "error")
        return redirect(url_for("pos_panel"))

    # Convertir ObjectId a str para la plantilla
    pedido["_id"] = str(pedido["_id"])

    # Aquí puedes pasar info adicional del pago si la tienes
    return render_template("ver_detalles_pago.html", pedido=pedido)



@app.route("/pos/ventas", methods=["GET"])
def historial_ventas():
    # Obtener la fecha del query param, si no hay, usar hoy
    fecha_str = request.args.get("fecha")
    if fecha_str:
        try:
            fecha_consulta = datetime.datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            fecha_consulta = datetime.date.today()
    else:
        fecha_consulta = datetime.date.today()

    # Configurar zona horaria local
    zona_local = pytz.timezone("America/Guayaquil")
    inicio = zona_local.localize(datetime.datetime.combine(fecha_consulta, datetime.time.min))
    fin = zona_local.localize(datetime.datetime.combine(fecha_consulta, datetime.time.max))

    # Buscar todos los pedidos pagados en el rango de fechas
    ventas = list(pedidos_col.find({
        "estado": "Pagado",
        "fecha_pago": {"$gte": inicio, "$lte": fin}
    }).sort("fecha_pago", -1))

    # Convertir fecha_pago a hora local para mostrar en template
    for venta in ventas:
        if "fecha_pago" in venta and venta["fecha_pago"]:
            venta["fecha_pago_local"] = venta["fecha_pago"].astimezone(zona_local)
        else:
            venta["fecha_pago_local"] = None

    # Calcular total del día
    total_dia = sum(venta.get("total", 0) for venta in ventas)

    # Pasar todo al template
    return render_template(
        "historial_ventas.html",
        ventas=ventas,
        fecha=fecha_consulta,
        total_dia=total_dia
    )



@app.route("/pos/pagar/<pedido_id>", methods=["GET", "POST"])
def pagar_pedido(pedido_id):
    pedido = pedidos_col.find_one({"_id": ObjectId(pedido_id)})
    if not pedido:
        flash("Pedido no encontrado", "error")
        return redirect(url_for("pos_panel"))

    if request.method == "POST":
        metodo_pago = request.form.get("metodo_pago", "").strip()
        utc_now = datetime.datetime.utcnow()

        if metodo_pago == "Efectivo":
            try:
                monto_entregado = float(request.form.get("monto_entregado", 0))
            except ValueError:
                flash("Monto entregado inválido", "error")
                return redirect(url_for("pagar_pedido", pedido_id=pedido_id))

            historial_pago = {
                "fecha": utc_now,
                "metodo_pago": metodo_pago,
                "monto_entregado": monto_entregado
            }

            pedidos_col.update_one(
                {"_id": ObjectId(pedido_id)},
                {
                    "$set": {
                        "estado": "Pagado",
                        "metodo_pago": metodo_pago,
                        "fecha_pago": utc_now,
                        "monto_entregado": monto_entregado
                    },
                    "$push": {"historial_pagos": historial_pago}
                }
            )
            flash(f"Pago registrado correctamente ({metodo_pago})", "success")

        elif metodo_pago == "Credito":
            try:
                monto_abono = float(request.form.get("monto_abono", 0))
            except ValueError:
                monto_abono = 0.0

            historial_credito = pedido.get("historial_creditos", [])
            saldo_restante = max(pedido["total"] - sum(p["monto"] for p in historial_credito) - monto_abono, 0.0)

            abono = {
                "fecha": utc_now,
                "monto": monto_abono,
                "saldo_restante": saldo_restante
            }

            nuevo_estado = "Pagado" if saldo_restante == 0 else "Crédito"

            update_data = {
                "$push": {"historial_creditos": abono},
                "$set": {"estado": nuevo_estado}
            }

            # Si se paga todo, agregamos fecha_pago
            if nuevo_estado == "Pagado":
                update_data["$set"]["fecha_pago"] = utc_now

            pedidos_col.update_one(
                {"_id": ObjectId(pedido_id)},
                update_data
            )
            flash(f"Crédito registrado correctamente (Abono: ${monto_abono:.2f})", "success")

        else:  # Transferencia u otros
            historial_pago = {
                "fecha": utc_now,
                "metodo_pago": metodo_pago
            }
            pedidos_col.update_one(
                {"_id": ObjectId(pedido_id)},
                {
                    "$set": {
                        "estado": "Pagado",
                        "metodo_pago": metodo_pago,
                        "fecha_pago": utc_now
                    },
                    "$push": {"historial_pagos": historial_pago}
                }
            )
            flash(f"Pago registrado correctamente ({metodo_pago})", "success")

        return redirect(url_for("pos_panel"))

    # Convertir _id a str para template
    pedido["_id"] = str(pedido["_id"])
    return render_template("pagar_pedido.html", pedido=pedido)




@app.route("/pos/pedido/<pedido_id>/agregar_producto", methods=["POST"])
def pos_agregar_producto(pedido_id):
    data = request.json
    producto_id = data.get("producto_id")
    cantidad = int(data.get("cantidad", 1))

    pedido = pedidos_col.find_one({"_id": ObjectId(pedido_id)})
    if not pedido:
        return jsonify({"error": "Pedido no encontrado"}), 404

    producto = productos_col.find_one({"_id": ObjectId(producto_id)})
    if not producto:
        return jsonify({"error": "Producto no encontrado"}), 404

    # Precio unitario según categoría
    precio_unitario = producto.get("precio", 0)

    # Lista de productos del pedido
    productos = pedido.get("productos", [])
    encontrado = False

    for p in productos:
        if str(p["producto_id"]) == str(producto_id):
            p["cantidad"] += cantidad
            encontrado = True
            break

    if not encontrado:
        productos.append({
            "producto_id": producto["_id"],
            "nombre": producto["nombre"],
            "cantidad": cantidad,
            "precio_unitario": precio_unitario
        })

    # ✅ Actualizar stock si es bebida
    if producto.get("categoria") == "bebida" and producto.get("stock") is not None:
        nuevo_stock = max(producto["stock"] - cantidad, 0)
        productos_col.update_one({"_id": producto["_id"]}, {"$set": {"stock": nuevo_stock}})

    # Recalcular total
    total = sum(p["cantidad"] * p["precio_unitario"] for p in productos)

    pedidos_col.update_one(
        {"_id": ObjectId(pedido_id)},
        {"$set": {"productos": productos, "total": total}}
    )

    # Convertir ObjectId a string para JSON
    for p in productos:
        p["producto_id"] = str(p["producto_id"])

    return jsonify({"productos": productos, "total": total})




@app.route("/pos/pedido/<pedido_id>/actualizar_cliente", methods=["POST"])
def pos_actualizar_cliente(pedido_id):
    data = request.json
    cliente = data.get("cliente", "").strip()
    if not cliente:
        return jsonify({"error": "Nombre cliente vacío"}), 400

    pedidos_col.update_one({"_id": ObjectId(pedido_id)}, {"$set": {"cliente": cliente}})
    return jsonify({"cliente": cliente})


@app.route("/pos/pedido/<pedido_id>/cambiar_estado", methods=["POST"])
def pos_cambiar_estado(pedido_id):
    data = request.json
    nuevo_estado = data.get("estado")
    if nuevo_estado not in ["Pendiente", "Pagado", "Cancelado"]:
        return jsonify({"error": "Estado inválido"}), 400

    pedidos_col.update_one({"_id": ObjectId(pedido_id)}, {"$set": {"estado": nuevo_estado}})
    return jsonify({"estado": nuevo_estado})



@app.route("/pos/historial_creditos")
def historial_creditos():
    pedidos_credito = list(pedidos_col.find({"estado": "Crédito"}))
    clientes_credito = {}

    for pedido in pedidos_credito:
        cliente = pedido.get("cliente", "Cliente sin nombre")
        historial = pedido.get("historial_creditos", [])
        saldo_actual = pedido["total"]
        # Creamos nuevo historial con saldo correcto
        historial_con_saldo = []
        for abono in historial:
            monto = abono.get("monto", 0)
            saldo_actual -= monto
            historial_con_saldo.append({
                "fecha": abono.get("fecha"),
                "monto": monto,
                "saldo_restante": max(saldo_actual, 0)  # nunca negativo
            })

        total_adeudado = saldo_actual
        if total_adeudado <= 0:
            continue  # ya pagó todo

        if cliente not in clientes_credito:
            clientes_credito[cliente] = {
                "total_adeudado": 0.0,
                "pedidos": []
            }

        clientes_credito[cliente]["total_adeudado"] += total_adeudado
        clientes_credito[cliente]["pedidos"].append({
            "pedido_id": str(pedido["_id"]),
            "descripcion": pedido.get("descripcion", ""),
            "total": pedido["total"],
            "historial": historial_con_saldo,
            "saldo_restante": total_adeudado
        })

    return render_template("historial_creditos.html", clientes_credito=clientes_credito)



@app.route("/pos/abonar/<pedido_id>", methods=["GET", "POST"])
def abonar_credito(pedido_id):
    pedido = pedidos_col.find_one({"_id": ObjectId(pedido_id)})
    if not pedido:
        flash("Pedido no encontrado", "error")
        return redirect(url_for("historial_creditos"))

    if "historial_creditos" not in pedido:
        pedido["historial_creditos"] = []

    total_abonado = sum(p["monto"] for p in pedido["historial_creditos"])
    saldo_restante = pedido["total"] - total_abonado

    if request.method == "POST":
        monto_abono = float(request.form.get("monto_abono", 0))
        if monto_abono <= 0 or monto_abono > saldo_restante:
            flash(f"Monto inválido. Saldo restante: ${saldo_restante:.2f}", "error")
            return redirect(url_for("abonar_credito", pedido_id=pedido_id))

        abono = {
            "fecha": datetime.datetime.utcnow(),
            "monto": monto_abono
        }

        pedidos_col.update_one(
            {"_id": ObjectId(pedido_id)},
            {"$push": {"historial_creditos": abono}}
        )

        flash(f"Abono de ${monto_abono:.2f} registrado correctamente", "success")
        return redirect(url_for("historial_creditos"))

    return render_template("abonar_credito.html", pedido=pedido, saldo_restante=saldo_restante)



@app.route('/pos/credito/<pedido_id>/detalle')
def ver_detalle_credito(pedido_id):
    pedido = pedidos_col.find_one({"_id": ObjectId(pedido_id)})
    if not pedido:
        flash("Pedido no encontrado", "error")
        return redirect(url_for("historial_creditos"))

    # Calcular saldo restante en base a los abonos registrados
    abonos = pedido.get("historial_creditos", []) or []
    try:
        total = float(pedido.get("total", 0) or 0)
    except (TypeError, ValueError):
        total = 0.0

    saldo = total
    for ab in abonos:
        try:
            saldo -= float(ab.get("monto", 0) or 0)
        except (TypeError, ValueError):
            pass
    if saldo < 0:
        saldo = 0.0

    # Preparar para la plantilla
    pedido["_id"] = str(pedido["_id"])
    pedido["saldo_restante"] = saldo

    # (Opcional) ordenar historial por fecha asc
    abonos_ordenados = sorted(abonos, key=lambda x: x.get("fecha") or datetime.datetime.min)

    return render_template("ver_detalle_credito.html", pedido=pedido, historial=abonos_ordenados)






if __name__ == "__main__":
    app.run(debug=True)


