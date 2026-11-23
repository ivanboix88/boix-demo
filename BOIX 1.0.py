
import streamlit as st
import sqlite3
import pandas as pd
from datetime import date
from pathlib import Path
import altair as alt
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor


# ----------------------------------
# CONFIGURACIÓN BOIX 1.0
# ----------------------------------

MODO_DEMO = True

# ----------------------------------
# CONFIGURACIÓN
# ----------------------------------

st.set_page_config(
    page_title="BOIX | Gestión Administrativa",
    page_icon="💙",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background-color: #F4F7FB;
}
[data-testid="stSidebar"] {
    background-color: #10243A;
}
[data-testid="stSidebar"] * {
    color: white;
}
h1, h2, h3 {
    color: #10243A;
}
.stButton button {
    border-radius: 8px;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

# ----------------------------------
# BASE DE DATOS
# ----------------------------------



def conectar():
    ruta_db = Path(__file__).resolve().parent / "boix.db"

    if MODO_DEMO:
        conexion = sqlite3.connect(
            ruta_db.as_uri() + "?mode=ro",
            uri=True
        )
        conexion.execute("PRAGMA query_only = ON")
        return conexion

    return sqlite3.connect(str(ruta_db))


def crear_tabla():
    conexion = conectar()
    conexion.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL,
            nombre TEXT NOT NULL,
            nif TEXT,
            email TEXT,
            telefono TEXT,
            fecha_alta TEXT
        )
    """)
    conexion.commit()
    conexion.close()


def crear_tabla_proveedores():
    conexion = conectar()
    conexion.execute("""
        CREATE TABLE IF NOT EXISTS proveedores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL,
            contacto TEXT NOT NULL,
            nif TEXT,
            email TEXT,
            telefono TEXT,
            direccion TEXT,
            categoria TEXT,
            fecha_alta TEXT
        )
    """)
    conexion.commit()
    conexion.close()


def crear_tabla_pedidos():
    conexion = conectar()

    conexion.execute("""
        CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referencia TEXT UNIQUE NOT NULL,
            proveedor_id INTEGER NOT NULL,
            fecha_pedido TEXT NOT NULL,
            fecha_entrega TEXT,
            estado TEXT NOT NULL DEFAULT 'Pendiente',
            observaciones TEXT
        )
    """)

    conexion.execute("""
        CREATE TABLE IF NOT EXISTS lineas_pedido (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id INTEGER NOT NULL,
            producto TEXT NOT NULL,
            cantidad REAL NOT NULL,
            precio_unitario REAL NOT NULL
        )
    """)

    columnas = [
        fila[1]
        for fila in conexion.execute(
            "PRAGMA table_info(lineas_pedido)"
        ).fetchall()
    ]

    if "producto_id" not in columnas:
        conexion.execute("""
            ALTER TABLE lineas_pedido
            ADD COLUMN producto_id INTEGER
        """)

    if "recepcion_registrada" not in columnas:
        conexion.execute("""
            ALTER TABLE lineas_pedido
            ADD COLUMN recepcion_registrada INTEGER
            NOT NULL DEFAULT 0
        """)

    conexion.commit()
    conexion.close()







# ----------------------------------
# INVENTARIO
# ----------------------------------

def crear_tabla_inventario():
    conexion = conectar()

    conexion.execute("""
        CREATE TABLE IF NOT EXISTS inventario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referencia TEXT UNIQUE NOT NULL,
            producto TEXT NOT NULL,
            categoria TEXT,
            proveedor_id INTEGER,
            ubicacion TEXT,
            stock_actual REAL NOT NULL DEFAULT 0,
            stock_minimo REAL NOT NULL DEFAULT 0,
            precio_unitario REAL NOT NULL DEFAULT 0,
            fecha_alta TEXT
        )
    """)

    conexion.commit()
    conexion.close()


def obtener_inventario():
    conexion = conectar()

    datos = pd.read_sql_query("""
        SELECT i.*, p.empresa AS proveedor
        FROM inventario i
        LEFT JOIN proveedores p
        ON i.proveedor_id = p.id
        ORDER BY i.referencia
    """, conexion)

    conexion.close()
    return datos


def guardar_producto(referencia, producto, categoria,
                     proveedor_id, ubicacion, stock_actual,
                     stock_minimo, precio_unitario):

    conexion = conectar()

    with conexion:
        conexion.execute("""
            INSERT INTO inventario
            (referencia, producto, categoria, proveedor_id,
             ubicacion, stock_actual, stock_minimo,
             precio_unitario, fecha_alta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            referencia, producto, categoria,
            proveedor_id, ubicacion, stock_actual,
            stock_minimo, precio_unitario,
            str(date.today())
        ))

    conexion.close()




def actualizar_producto(id_producto, referencia, producto,
                        categoria, proveedor_id, ubicacion,
                        stock_actual, stock_minimo,
                        precio_unitario):

    conexion = conectar()

    try:
        with conexion:
            conexion.execute("""
                UPDATE inventario
                SET referencia = ?,
                    producto = ?,
                    categoria = ?,
                    proveedor_id = ?,
                    ubicacion = ?,
                    stock_minimo = ?,
                    precio_unitario = ?
                WHERE id = ?
            """, (
                referencia, producto, categoria,
                proveedor_id, ubicacion,
                stock_minimo,
                precio_unitario, id_producto
            ))
    finally:
        conexion.close()




def eliminar_producto(id_producto):

    conexion = conectar()

    try:
        with conexion:

            conexion.execute("BEGIN IMMEDIATE")

            pedidos = conexion.execute("""
                SELECT COUNT(*)
                FROM lineas_pedido
                WHERE producto_id = ?
            """, (id_producto,)).fetchone()[0]

            movimientos = conexion.execute("""
                SELECT COUNT(*)
                FROM movimientos
                WHERE producto_id = ?
            """, (id_producto,)).fetchone()[0]

            if pedidos > 0 or movimientos > 0:
                raise ValueError(
                    "No se puede eliminar un producto "
                    "con pedidos o movimientos registrados."
                )

            conexion.execute("""
                DELETE FROM inventario
                WHERE id = ?
            """, (id_producto,))

    finally:
        conexion.close()






# ----------------------------------
# MOVIMIENTOS DE ALMACÉN
# ----------------------------------

def crear_tabla_movimientos():

    conexion = conectar()

    conexion.execute("""
        CREATE TABLE IF NOT EXISTS movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL,
            referencia TEXT NOT NULL,
            producto TEXT NOT NULL,
            tipo TEXT NOT NULL,
            cantidad REAL NOT NULL,
            stock_anterior REAL NOT NULL,
            stock_resultante REAL NOT NULL,
            fecha TEXT NOT NULL,
            motivo TEXT,
            observaciones TEXT
        )
    """)

    conexion.commit()
    conexion.close()



def registrar_movimiento(producto_id, tipo, cantidad,
                          motivo, observaciones):

    conexion = conectar()

    try:
        with conexion:

            conexion.execute("BEGIN IMMEDIATE")

            registro = conexion.execute("""
                SELECT referencia, producto, stock_actual
                FROM inventario
                WHERE id = ?
            """, (producto_id,)).fetchone()

            if registro is None:
                raise ValueError("El producto no existe.")

            if cantidad <= 0:
                raise ValueError("La cantidad debe ser positiva.")

            referencia, producto, stock_anterior = registro

            if tipo == "Entrada":

                stock_resultante = stock_anterior + cantidad

            elif tipo == "Salida":

                if cantidad > stock_anterior:
                    raise ValueError("Stock insuficiente.")

                stock_resultante = stock_anterior - cantidad

            else:
                raise ValueError("Movimiento no válido.")

            conexion.execute("""
                UPDATE inventario
                SET stock_actual = ?
                WHERE id = ?
            """, (stock_resultante, producto_id))

            conexion.execute("""
                INSERT INTO movimientos
                (producto_id, referencia, producto, tipo,
                 cantidad, stock_anterior, stock_resultante,
                 fecha, motivo, observaciones)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                producto_id,
                referencia,
                producto,
                tipo,
                cantidad,
                stock_anterior,
                stock_resultante,
                str(date.today()),
                motivo,
                observaciones
            ))

    finally:
        conexion.close()


def obtener_movimientos():

    conexion = conectar()

    datos = pd.read_sql_query("""
        SELECT *
        FROM movimientos
        ORDER BY id DESC
    """, conexion)

    conexion.close()

    return datos



def guardar_proveedor(empresa, contacto, nif, email, telefono, direccion, categoria):
    conexion = conectar()
    conexion.execute("""
        INSERT INTO proveedores
        (empresa, contacto, nif, email, telefono, direccion, categoria, fecha_alta)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        empresa, contacto, nif, email, telefono,
        direccion, categoria, str(date.today())
    ))
    conexion.commit()
    conexion.close()



def obtener_proveedores():
    conexion = conectar()
    datos = pd.read_sql_query(
        "SELECT * FROM proveedores ORDER BY id DESC",
        conexion
    )
    conexion.close()
    return datos

def actualizar_proveedor(id_proveedor, empresa, contacto, nif, email, telefono, direccion, categoria):
    conexion = conectar()

    conexion.execute("""
        UPDATE proveedores
        SET empresa = ?, contacto = ?, nif = ?, email = ?,
            telefono = ?, direccion = ?, categoria = ?
        WHERE id = ?
    """, (
        empresa, contacto, nif, email,
        telefono, direccion, categoria, id_proveedor
    ))

    conexion.commit()
    conexion.close()


def eliminar_proveedor(id_proveedor):
    conexion = conectar()

    try:
        with conexion:
            conexion.execute("BEGIN IMMEDIATE")

            pedidos = conexion.execute(
                "SELECT COUNT(*) FROM pedidos WHERE proveedor_id = ?",
                (id_proveedor,)
            ).fetchone()[0]

            facturas = conexion.execute(
                "SELECT COUNT(*) FROM facturas WHERE proveedor_id = ?",
                (id_proveedor,)
            ).fetchone()[0]

            productos = conexion.execute(
                "SELECT COUNT(*) FROM inventario WHERE proveedor_id = ?",
                (id_proveedor,)
            ).fetchone()[0]

            incidencias = conexion.execute(
                "SELECT COUNT(*) FROM incidencias WHERE proveedor_id = ?",
                (id_proveedor,)
            ).fetchone()[0]

            if pedidos or facturas or productos or incidencias:
                raise ValueError(
                    "No se puede eliminar este proveedor porque "
                    "tiene pedidos, facturas, productos o "
                    "incidencias asociados."
                )

            conexion.execute(
                "DELETE FROM proveedores WHERE id = ?",
                (id_proveedor,)
            )

    finally:
        conexion.close()

def guardar_cliente(empresa, nombre, nif, email, telefono):

    if MODO_DEMO:
        raise PermissionError(
            "Modo demostración: no se permite modificar los datos."
        )

    conexion = conectar()
    conexion.execute("""
        INSERT INTO clientes
        (empresa, nombre, nif, email, telefono, fecha_alta)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (empresa, nombre, nif, email, telefono, str(date.today())))
    conexion.commit()
    conexion.close()


def obtener_clientes():
    conexion = conectar()
    datos = pd.read_sql_query(
        "SELECT * FROM clientes ORDER BY id DESC",
        conexion
    )
    conexion.close()
    return datos

def actualizar_cliente(id_cliente, empresa, nombre, nif, email, telefono):
    conexion = conectar()
    conexion.execute("""
        UPDATE clientes
        SET empresa=?, nombre=?, nif=?, email=?, telefono=?
        WHERE id=?
    """, (empresa, nombre, nif, email, telefono, id_cliente))
    conexion.commit()
    conexion.close()

def eliminar_cliente(id_cliente):
    conexion = conectar()
    conexion.execute(
        "DELETE FROM clientes WHERE id=?",
        (id_cliente,)
    )
    conexion.commit()
    conexion.close()
# ----------------------------------
# BASE DE DATOS DE FACTURACIÓN
# ----------------------------------

# ----------------------------------
# BASE DE DATOS DE INCIDENCIAS
# ----------------------------------

# ----------------------------------
# FUNCIONES DE INCIDENCIAS
# ----------------------------------

def generar_referencia_incidencia():
    conexion = conectar()

    try:
        anio = date.today().year
        prefijo = f"INC-{anio}-"

        resultado = conexion.execute(
            """
            SELECT referencia
            FROM incidencias
            WHERE referencia LIKE ?
            ORDER BY id DESC
            """,
            (f"{prefijo}%",)
        ).fetchall()

        numeros = []

        for (referencia,) in resultado:
            try:
                numeros.append(int(referencia.split("-")[-1]))
            except (ValueError, AttributeError):
                continue

        siguiente = max(numeros, default=0) + 1

        return f"{prefijo}{siguiente:04d}"

    finally:
        conexion.close()


def guardar_incidencia(
    titulo,
    descripcion,
    tipo,
    prioridad,
    proveedor_id,
    pedido_id,
    responsable,
    observaciones
):
    conexion = conectar()

    try:
        referencia = generar_referencia_incidencia()

        conexion.execute(
            """
            INSERT INTO incidencias (
                referencia,
                titulo,
                descripcion,
                tipo,
                prioridad,
                estado,
                proveedor_id,
                pedido_id,
                fecha_apertura,
                responsable,
                observaciones
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                referencia,
                titulo,
                descripcion,
                tipo,
                prioridad,
                "Abierta",
                proveedor_id,
                pedido_id,
                date.today().isoformat(),
                responsable,
                observaciones
            )
        )

        conexion.commit()
        return referencia

    finally:
        conexion.close()


def actualizar_incidencia(id_incidencia, estado, solucion):

    conexion = conectar()

    try:
        fecha_resolucion = (
            date.today().isoformat()
            if estado == "Resuelta"
            else None
        )

        conexion.execute(
            """
            UPDATE incidencias
            SET estado = ?,
                solucion = ?,
                fecha_resolucion = ?
            WHERE id = ?
            """,
            (
                estado,
                solucion,
                fecha_resolucion,
                id_incidencia
            )
        )

        conexion.commit()

    finally:
        conexion.close()

def obtener_incidencia_por_id(id_incidencia):
    conexion = conectar()
    try:
        return conexion.execute(
            """
            SELECT titulo, descripcion, tipo, prioridad,
                   responsable, observaciones
            FROM incidencias
            WHERE id = ?
            """,
            (id_incidencia,)
        ).fetchone()
    finally:
        conexion.close()


def editar_incidencia(id_incidencia, titulo, descripcion,
                     tipo, prioridad, responsable, observaciones):
    conexion = conectar()
    try:
        with conexion:
            conexion.execute(
                """
                UPDATE incidencias
                SET titulo = ?,
                    descripcion = ?,
                    tipo = ?,
                    prioridad = ?,
                    responsable = ?,
                    observaciones = ?
                WHERE id = ?
                """,
                (
                    titulo, descripcion, tipo, prioridad,
                    responsable, observaciones, id_incidencia
                )
            )
    finally:
        conexion.close()

def obtener_incidencias():
    conexion = conectar()

    try:
        return pd.read_sql_query(
            """
            SELECT
                i.id,
                i.referencia,
                i.titulo,
                i.tipo,
                i.prioridad,
                i.estado,
                i.fecha_apertura,
                i.fecha_resolucion,
                i.responsable,
                p.empresa AS proveedor
            FROM incidencias i
            LEFT JOIN proveedores p
                ON i.proveedor_id = p.id
            ORDER BY i.id DESC
            """,
            conexion
        )

    finally:
        conexion.close()

def crear_tabla_incidencias():

    conexion = conectar()

    try:
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS incidencias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referencia TEXT UNIQUE NOT NULL,
                titulo TEXT NOT NULL,
                descripcion TEXT NOT NULL,
                tipo TEXT NOT NULL,
                prioridad TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'Abierta',
                proveedor_id INTEGER,
                pedido_id INTEGER,
                fecha_apertura TEXT NOT NULL,
                fecha_resolucion TEXT,
                responsable TEXT,
                solucion TEXT,
                observaciones TEXT,
                FOREIGN KEY (proveedor_id)
                    REFERENCES proveedores(id),
                FOREIGN KEY (pedido_id)
                    REFERENCES pedidos(id)
            )
        """)

        conexion.commit()

    finally:
        conexion.close()

def crear_tabla_facturas():

    conexion = conectar()

    conexion.execute("""
        CREATE TABLE IF NOT EXISTS facturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referencia TEXT UNIQUE NOT NULL,
            numero_proveedor TEXT NOT NULL,
            pedido_id INTEGER UNIQUE NOT NULL,
            proveedor_id INTEGER NOT NULL,
            proveedor TEXT NOT NULL,
            fecha_emision TEXT NOT NULL,
            fecha_vencimiento TEXT NOT NULL,
            base_imponible REAL NOT NULL,
            iva REAL NOT NULL,
            cuota_iva REAL NOT NULL,
            importe_total REAL NOT NULL,
            estado TEXT NOT NULL DEFAULT 'Pendiente',
            fecha_pago TEXT,
            observaciones TEXT
        )
    """)

    conexion.commit()
    conexion.close()

if not MODO_DEMO:
    crear_tabla()
    crear_tabla_proveedores()
    crear_tabla_pedidos()
    crear_tabla_inventario()
    crear_tabla_movimientos()
    crear_tabla_facturas()
    crear_tabla_incidencias()

# ----------------------------------
# FUNCIONES DE PEDIDOS
# ----------------------------------
def generar_referencia_pedido():
    conexion = conectar()
    try:
        prefijo = f"PED-{date.today().year}-"

        resultado = conexion.execute("""
            SELECT MAX(CAST(SUBSTR(referencia, ?) AS INTEGER))
            FROM pedidos
            WHERE referencia LIKE ?
        """, (len(prefijo) + 1, prefijo + "%")).fetchone()

        siguiente = (resultado[0] or 0) + 1

        referencia = f"{prefijo}{siguiente:03d}"

        while conexion.execute(
            "SELECT 1 FROM pedidos WHERE referencia = ?",
            (referencia,)
        ).fetchone():
            siguiente += 1
            referencia = f"{prefijo}{siguiente:03d}"

        return referencia
    finally:
        conexion.close()

def obtener_pedidos():
    conexion = conectar()
    datos = pd.read_sql_query("""
        SELECT p.id, p.referencia, pr.empresa AS proveedor,
               p.fecha_pedido, p.fecha_entrega, p.estado, p.observaciones
        FROM pedidos p
        LEFT JOIN proveedores pr ON pr.id = p.proveedor_id
        ORDER BY p.id DESC
    """, conexion)
    conexion.close()
    return datos


def obtener_pedido_por_id(id_pedido):
    conexion = conectar()
    pedido = pd.read_sql_query("""
    SELECT p.*, pr.empresa AS proveedor
    FROM pedidos p
    LEFT JOIN proveedores pr ON pr.id = p.proveedor_id
    WHERE p.id = ?
""", conexion, params=(id_pedido,))
    lineas = pd.read_sql_query(
        "SELECT * FROM lineas_pedido WHERE pedido_id = ?",
        conexion,
        params=(id_pedido,)
    )
    conexion.close()
    return pedido, lineas



def guardar_pedido(referencia, proveedor_id, fecha_pedido,
                  fecha_entrega, estado, observaciones,
                  producto, cantidad, precio_unitario,
                  producto_id=None):

    conexion = conectar()

    try:
        with conexion:

            cursor = conexion.execute("""
                INSERT INTO pedidos
                (referencia, proveedor_id, fecha_pedido,
                 fecha_entrega, estado, observaciones)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                referencia,
                proveedor_id,
                str(fecha_pedido),
                str(fecha_entrega) if fecha_entrega else None,
                estado,
                observaciones
            ))

            id_pedido = cursor.lastrowid

            conexion.execute("""
                INSERT INTO lineas_pedido
                (pedido_id, producto, cantidad,
                 precio_unitario, producto_id,
                 recepcion_registrada)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                id_pedido,
                producto,
                cantidad,
                precio_unitario,
                producto_id,
                0
            ))


            if estado == "Entregado":
                registrar_recepcion_pedido(
                    conexion,
                    id_pedido
                )

        return id_pedido

    finally:
        conexion.close()






def actualizar_pedido(id_pedido, proveedor_id, fecha_pedido,
                      fecha_entrega, estado, observaciones,
                      producto, cantidad, precio_unitario):

    conexion = conectar()

    try:
        with conexion:

            conexion.execute("BEGIN IMMEDIATE")
            factura = conexion.execute("""
                SELECT id FROM facturas
                WHERE pedido_id = ?
            """, (id_pedido,)).fetchone()

            if factura:
                raise ValueError(
                    "No se puede modificar un pedido ya facturado."
                )
            recepcion = conexion.execute("""
                SELECT COUNT(*)
                FROM lineas_pedido
                WHERE pedido_id = ?
                AND recepcion_registrada = 1
            """, (id_pedido,)).fetchone()[0]

            if recepcion > 0:
                raise ValueError(
                    "No se puede editar un pedido "
                    "que ya ha generado una entrada de stock."
                )

            conexion.execute("""
                UPDATE pedidos
                SET proveedor_id = ?,
                    fecha_pedido = ?,
                    fecha_entrega = ?,
                    estado = ?,
                    observaciones = ?
                WHERE id = ?
            """, (
                proveedor_id,
                str(fecha_pedido),
                str(fecha_entrega) if fecha_entrega else None,
                estado,
                observaciones,
                id_pedido
            ))

            conexion.execute("""
                UPDATE lineas_pedido
                SET producto = ?,
                    cantidad = ?,
                    precio_unitario = ?
                WHERE pedido_id = ?
            """, (
                producto,
                cantidad,
                precio_unitario,
                id_pedido
            ))

            if estado == "Entregado":
                registrar_recepcion_pedido(conexion, id_pedido)

    finally:
        conexion.close()




def eliminar_pedido(id_pedido):

    conexion = conectar()

    try:
        with conexion:

            conexion.execute("BEGIN IMMEDIATE")
            factura = conexion.execute("""
                SELECT id FROM facturas
                WHERE pedido_id = ?
            """, (id_pedido,)).fetchone()

            if factura:
                raise ValueError(
                    "No se puede eliminar un pedido ya facturado."
                )
            recepcion = conexion.execute("""
                SELECT COUNT(*)
                FROM lineas_pedido
                WHERE pedido_id = ?
                AND recepcion_registrada = 1
            """, (id_pedido,)).fetchone()[0]

            if recepcion > 0:
                raise ValueError(
                    "No se puede eliminar un pedido "
                    "que ya ha generado una entrada de stock."
                )

            conexion.execute(
                "DELETE FROM lineas_pedido WHERE pedido_id = ?",
                (id_pedido,)
            )

            conexion.execute(
                "DELETE FROM pedidos WHERE id = ?",
                (id_pedido,)
            )

    finally:
        conexion.close()




def registrar_recepcion_pedido(conexion, id_pedido):

    lineas = conexion.execute("""
        SELECT id, producto_id, cantidad
        FROM lineas_pedido
        WHERE pedido_id = ?
        AND producto_id IS NOT NULL
        AND recepcion_registrada = 0
    """, (id_pedido,)).fetchall()

    for id_linea, producto_id, cantidad in lineas:

        registro = conexion.execute("""
            SELECT referencia, producto, stock_actual
            FROM inventario
            WHERE id = ?
        """, (producto_id,)).fetchone()

        if registro is None:
            raise ValueError("El producto no existe en inventario.")

        referencia, producto, stock_anterior = registro
        stock_resultante = stock_anterior + cantidad

        conexion.execute("""
            UPDATE inventario
            SET stock_actual = ?
            WHERE id = ?
        """, (stock_resultante, producto_id))

        conexion.execute("""
            INSERT INTO movimientos
            (producto_id, referencia, producto, tipo,
             cantidad, stock_anterior, stock_resultante,
             fecha, motivo, observaciones)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            producto_id,
            referencia,
            producto,
            "Entrada",
            cantidad,
            stock_anterior,
            stock_resultante,
            str(date.today()),
            "Recepción de pedido",
            f"Pedido ID: {id_pedido}"
        ))

        conexion.execute("""
            UPDATE lineas_pedido
            SET recepcion_registrada = 1
            WHERE id = ?
        """, (id_linea,))




def actualizar_estado_pedido(id_pedido, nuevo_estado):

    conexion = conectar()

    try:
        with conexion:

            conexion.execute("BEGIN IMMEDIATE")
            factura = conexion.execute("""
                SELECT id FROM facturas
                WHERE pedido_id = ?
            """, (id_pedido,)).fetchone()

            if factura and nuevo_estado == "Cancelado":
                raise ValueError(
                    "No se puede cancelar un pedido ya facturado."
                )
            recepcion = conexion.execute("""
                SELECT COUNT(*)
                FROM lineas_pedido
                WHERE pedido_id = ?
                AND recepcion_registrada = 1
            """, (id_pedido,)).fetchone()[0]

            if recepcion > 0 and nuevo_estado != "Entregado":
                raise ValueError(
                    "No se puede cambiar el estado de un pedido recibido."
                )

            conexion.execute("""
                UPDATE pedidos
                SET estado = ?
                WHERE id = ?
            """, (nuevo_estado, id_pedido))

            if nuevo_estado == "Entregado":
                registrar_recepcion_pedido(conexion, id_pedido)

    finally:
        conexion.close()



def obtener_total_pedidos():
    conexion = conectar()
    total = conexion.execute(
        "SELECT COUNT(*) FROM pedidos"
    ).fetchone()[0]
    conexion.close()
    return total
# ----------------------------------
# FUNCIONES DE FACTURACIÓN
# ----------------------------------

def obtener_facturas():

    conexion = conectar()

    datos = pd.read_sql_query("""
        SELECT f.*, p.referencia AS pedido
        FROM facturas f
        LEFT JOIN pedidos p
        ON f.pedido_id = p.id
        ORDER BY f.id DESC
    """, conexion)

    conexion.close()

    return datos


def obtener_pedidos_sin_factura():

    conexion = conectar()

    datos = pd.read_sql_query("""
        SELECT p.id, p.referencia,
               p.proveedor_id,
               pr.empresa AS proveedor,
               COALESCE(
                   SUM(lp.cantidad * lp.precio_unitario), 0
               ) AS base_imponible
        FROM pedidos p
        INNER JOIN proveedores pr
            ON p.proveedor_id = pr.id
        INNER JOIN lineas_pedido lp
            ON p.id = lp.pedido_id
        LEFT JOIN facturas f
            ON p.id = f.pedido_id
        WHERE f.id IS NULL
        AND p.estado != 'Cancelado'
        GROUP BY p.id
        ORDER BY p.id DESC
    """, conexion)

    conexion.close()

    return datos


def generar_referencia_factura(conexion):

    prefijo = f"FAC-{date.today().year}-"

    resultado = conexion.execute("""
        SELECT MAX(CAST(SUBSTR(referencia, ?) AS INTEGER))
        FROM facturas
        WHERE referencia LIKE ?
    """, (
        len(prefijo) + 1,
        prefijo + "%"
    )).fetchone()

    siguiente = (resultado[0] or 0) + 1

    return f"{prefijo}{siguiente:04d}"


def guardar_factura(pedido_id, numero_proveedor,
                    fecha_emision, fecha_vencimiento,
                    iva, observaciones):

    conexion = conectar()

    try:
        with conexion:

            conexion.execute("BEGIN IMMEDIATE")

            if fecha_vencimiento < fecha_emision:
                raise ValueError(
                    "El vencimiento no puede ser anterior a la emisión."
                )

            if not numero_proveedor.strip():
                raise ValueError(
                    "Introduce el número de factura del proveedor."
                )

            pedido = conexion.execute("""
                SELECT p.proveedor_id, pr.empresa,
                       SUM(lp.cantidad * lp.precio_unitario)
                FROM pedidos p
                INNER JOIN proveedores pr
                    ON p.proveedor_id = pr.id
                INNER JOIN lineas_pedido lp
                    ON p.id = lp.pedido_id
                WHERE p.id = ?
                AND p.estado != 'Cancelado'
                GROUP BY p.id
            """, (pedido_id,)).fetchone()

            if pedido is None:
                raise ValueError("Pedido no disponible.")

            proveedor_id, proveedor, base_imponible = pedido

            existe = conexion.execute("""
                SELECT id FROM facturas
                WHERE pedido_id = ?
                OR (proveedor_id = ? AND numero_proveedor = ?)
            """, (
                pedido_id,
                proveedor_id,
                numero_proveedor.strip()
            )).fetchone()

            if existe:
                raise ValueError("La factura ya está registrada.")

            base_imponible = round(base_imponible, 2)
            cuota_iva = round(base_imponible * iva / 100, 2)
            importe_total = round(base_imponible + cuota_iva, 2)

            referencia = generar_referencia_factura(conexion)

            conexion.execute("""
                INSERT INTO facturas (
                    referencia, numero_proveedor,
                    pedido_id, proveedor_id, proveedor,
                    fecha_emision, fecha_vencimiento,
                    base_imponible, iva, cuota_iva,
                    importe_total, estado, observaciones
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                referencia,
                numero_proveedor.strip(),
                pedido_id,
                proveedor_id,
                proveedor,
                str(fecha_emision),
                str(fecha_vencimiento),
                base_imponible,
                iva,
                cuota_iva,
                importe_total,
                "Pendiente",
                observaciones
            ))

        return referencia

    finally:
        conexion.close()

def generar_pdf_dashboard():

    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Table,
        TableStyle, Spacer
    )
    from reportlab.lib.styles import (
        getSampleStyleSheet, ParagraphStyle
    )
    from reportlab.lib import colors

    clientes = obtener_clientes()
    proveedores = obtener_proveedores()
    pedidos = obtener_pedidos()

    total_pedidos = obtener_total_pedidos()
    importe_total = obtener_importe_total_pedidos()

    estados = [
        "Pendiente",
        "En preparación",
        "Enviado",
        "Entregado",
        "Cancelado"
    ]

    conteo = pedidos["estado"].value_counts()

    buffer = BytesIO()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=45,
        leftMargin=45,
        topMargin=45,
        bottomMargin=45
    )

    estilos = getSampleStyleSheet()

    estilos.add(ParagraphStyle(
        name="DashboardTitulo",
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=HexColor("#10243A"),
        spaceAfter=18
    ))

    elementos = [
        Paragraph(
            "BOIX | INFORME DE ACTIVIDAD",
            estilos["DashboardTitulo"]
        ),
        Paragraph(
            f"Fecha de emisión: {date.today():%d/%m/%Y}",
            estilos["Normal"]
        ),
        Spacer(1, 25),
        Paragraph(
            "1. Indicadores generales",
            estilos["Heading2"]
        ),
        Spacer(1, 12)
    ]

    indicadores = [
        ["Indicador", "Resultado"],
        ["Clientes registrados", str(len(clientes))],
        ["Proveedores registrados", str(len(proveedores))],
        ["Pedidos registrados", str(total_pedidos)],
        ["Volumen de pedidos", f"{importe_total:,.2f} EUR"]
    ]

    def crear_tabla(datos):

        tabla = Table(
            datos,
            colWidths=[310, 190],
            repeatRows=1
        )

        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0),
             HexColor("#10243A")),
            ("TEXTCOLOR", (0, 0), (-1, 0),
             colors.white),
            ("FONTNAME", (0, 0), (-1, 0),
             "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, HexColor("#F4F7FB")]),
            ("LINEBELOW", (0, 0), (-1, -1),
             0.3, HexColor("#DCE3EB"))
        ]))

        return tabla

    elementos.append(crear_tabla(indicadores))
    elementos.append(Spacer(1, 30))

    elementos.append(
        Paragraph(
            "2. Seguimiento de pedidos",
            estilos["Heading2"]
        )
    )

    elementos.append(Spacer(1, 12))

    seguimiento = [["Estado", "Número de pedidos"]]

    for estado in estados:
        seguimiento.append([
            estado,
            str(int(conteo.get(estado, 0)))
        ])

    elementos.append(crear_tabla(seguimiento))
    elementos.append(Spacer(1, 30))

    elementos.append(
        Paragraph(
            "3. Resumen ejecutivo",
            estilos["Heading2"]
        )
    )

    elementos.append(Spacer(1, 10))

    elementos.append(
        Paragraph(
            f"BOIX registra actualmente {total_pedidos} "
            f"pedidos, con un volumen económico acumulado "
            f"de {importe_total:,.2f} EUR. "
            f"El sistema cuenta con {len(proveedores)} "
            f"proveedores y {len(clientes)} clientes registrados.",
            estilos["Normal"]
        )
    )

    elementos.append(Spacer(1, 35))

    elementos.append(
        Paragraph(
            "BOIX ERP | Informe interno de gestión empresarial",
            estilos["Normal"]
        )
    )

    documento.build(elementos)

    buffer.seek(0)
    return buffer.getvalue()

def generar_pdf_proveedores():

    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Table,
        TableStyle, Spacer
    )
    from reportlab.lib.styles import (
        getSampleStyleSheet, ParagraphStyle
    )
    from reportlab.lib import colors
    from xml.sax.saxutils import escape

    proveedores = obtener_proveedores()
    buffer = BytesIO()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=35,
        leftMargin=35,
        topMargin=45,
        bottomMargin=45
    )

    estilos = getSampleStyleSheet()

    estilos.add(ParagraphStyle(
        name="ProveedoresTitulo",
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=HexColor("#10243A"),
        spaceAfter=15
    ))

    estilos.add(ParagraphStyle(
        name="ProveedoresCelda",
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        wordWrap="CJK"
    ))

    elementos = [
        Paragraph(
            "BOIX | DIRECTORIO DE PROVEEDORES",
            estilos["ProveedoresTitulo"]
        ),
        Paragraph(
            f"Fecha de emisión: {date.today():%d/%m/%Y}",
            estilos["Normal"]
        ),
        Spacer(1, 15),
        Paragraph(
            f"Proveedores registrados: {len(proveedores)}",
            estilos["Normal"]
        ),
        Spacer(1, 20)
    ]

    if proveedores.empty:

        elementos.append(
            Paragraph(
                "No hay proveedores registrados.",
                estilos["Normal"]
            )
        )

    else:

        datos = [[
            "Empresa",
            "Contacto",
            "NIF / CIF",
            "Categoría",
            "Teléfono"
        ]]

        for _, fila in proveedores.iterrows():

            datos.append([
                Paragraph(
                    escape(str(fila[columna] or "")),
                    estilos["ProveedoresCelda"]
                )
                for columna in [
                    "empresa", "contacto", "nif",
                    "categoria", "telefono"
                ]
            ])

        tabla = Table(
            datos,
            colWidths=[130, 110, 90, 110, 80],
            repeatRows=1,
            hAlign="LEFT"
        )

        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0),
             HexColor("#10243A")),
            ("TEXTCOLOR", (0, 0), (-1, 0),
             colors.white),
            ("FONTNAME", (0, 0), (-1, 0),
             "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, HexColor("#F4F7FB")]),
            ("LINEBELOW", (0, 0), (-1, -1),
             0.3, HexColor("#DCE3EB"))
        ]))

        elementos.append(tabla)

    elementos.append(Spacer(1, 25))

    elementos.append(
        Paragraph(
            "BOIX ERP | Documento de control interno",
            estilos["Normal"]
        )
    )

    documento.build(elementos)

    buffer.seek(0)
    return buffer.getvalue()

def generar_pdf_incidencias():

    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Table,
        TableStyle, Spacer
    )
    from reportlab.lib.styles import (
        getSampleStyleSheet, ParagraphStyle
    )
    from reportlab.lib import colors
    from xml.sax.saxutils import escape

    incidencias = obtener_incidencias()
    buffer = BytesIO()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=35,
        leftMargin=35,
        topMargin=45,
        bottomMargin=45
    )

    estilos = getSampleStyleSheet()

    estilos.add(ParagraphStyle(
        name="IncidenciasTitulo",
        fontName="Helvetica-Bold",
        fontSize=20,
        textColor=HexColor("#10243A"),
        spaceAfter=15
    ))

    estilos.add(ParagraphStyle(
        name="IncidenciasCelda",
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        wordWrap="CJK"
    ))

    abiertas = len(incidencias[
        incidencias["estado"] == "Abierta"
    ])

    en_proceso = len(incidencias[
        incidencias["estado"] == "En proceso"
    ])

    resueltas = len(incidencias[
        incidencias["estado"] == "Resuelta"
    ])

    elementos = [
        Paragraph(
            "BOIX | INFORME DE INCIDENCIAS",
            estilos["IncidenciasTitulo"]
        ),
        Paragraph(
            f"Fecha: {date.today():%d/%m/%Y}",
            estilos["Normal"]
        ),
        Spacer(1, 15),
        Paragraph(
            f"Total: {len(incidencias)} | "
            f"Abiertas: {abiertas} | "
            f"En proceso: {en_proceso} | "
            f"Resueltas: {resueltas}",
            estilos["Normal"]
        ),
        Spacer(1, 20)
    ]

    if incidencias.empty:

        elementos.append(
            Paragraph(
                "No hay incidencias registradas.",
                estilos["Normal"]
            )
        )

    else:

        columnas = [
            "referencia",
            "titulo",
            "prioridad",
            "estado",
            "fecha_apertura"
        ]

        datos = [[
            "Referencia",
            "Incidencia",
            "Prioridad",
            "Estado",
            "Apertura"
        ]]

        for _, fila in incidencias.iterrows():

            datos.append([
                Paragraph(
                    escape(
                        "" if pd.isna(fila[columna])
                        else str(fila[columna])
                    ),
                    estilos["IncidenciasCelda"]
                )
                for columna in columnas
            ])

        tabla = Table(
            datos,
            colWidths=[100, 165, 70, 95, 90],
            repeatRows=1,
            hAlign="LEFT"
        )

        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0),
             HexColor("#10243A")),
            ("TEXTCOLOR", (0, 0), (-1, 0),
             colors.white),
            ("FONTNAME", (0, 0), (-1, 0),
             "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, HexColor("#F4F7FB")]),
            ("LINEBELOW", (0, 0), (-1, -1),
             0.3, HexColor("#DCE3EB"))
        ]))

        elementos.append(tabla)

    elementos.append(Spacer(1, 25))

    elementos.append(
        Paragraph(
            "BOIX ERP | Control de incidencias",
            estilos["Normal"]
        )
    )

    documento.build(elementos)

    buffer.seek(0)
    return buffer.getvalue()

def generar_pdf_clientes():

    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Table,
        TableStyle, Spacer
    )
    from reportlab.lib.styles import (
        getSampleStyleSheet, ParagraphStyle
    )
    from reportlab.lib import colors
    from xml.sax.saxutils import escape

    clientes = obtener_clientes()

    buffer = BytesIO()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=35,
        leftMargin=35,
        topMargin=45,
        bottomMargin=45
    )

    estilos = getSampleStyleSheet()

    estilos.add(ParagraphStyle(
        name="ClientesTitulo",
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=HexColor("#10243A"),
        spaceAfter=15
    ))

    estilos.add(ParagraphStyle(
        name="ClientesCelda",
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        wordWrap="CJK"
    ))

    elementos = [
        Paragraph(
            "BOIX | DIRECTORIO DE CLIENTES",
            estilos["ClientesTitulo"]
        ),
        Paragraph(
            f"Fecha de emisión: {date.today():%d/%m/%Y}",
            estilos["Normal"]
        ),
        Spacer(1, 15),
        Paragraph(
            f"Total de clientes registrados: {len(clientes)}",
            estilos["Normal"]
        ),
        Spacer(1, 20)
    ]

    if clientes.empty:

        elementos.append(
            Paragraph(
                "No hay clientes registrados.",
                estilos["Normal"]
            )
        )

    else:

        datos = [[
            "Empresa",
            "Contacto",
            "NIF / CIF",
            "Correo electrónico",
            "Teléfono"
        ]]

        for _, fila in clientes.iterrows():

            datos.append([
                Paragraph(
                    escape(str(fila[columna] or "")),
                    estilos["ClientesCelda"]
                )
                for columna in [
                    "empresa", "nombre", "nif",
                    "email", "telefono"
                ]
            ])

        tabla = Table(
            datos,
            colWidths=[115, 95, 75, 145, 90],
            repeatRows=1,
            hAlign="LEFT"
        )

        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0),
             HexColor("#10243A")),
            ("TEXTCOLOR", (0, 0), (-1, 0),
             colors.white),
            ("FONTNAME", (0, 0), (-1, 0),
             "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, HexColor("#F4F7FB")]),
            ("LINEBELOW", (0, 0), (-1, -1),
             0.3, HexColor("#DCE3EB"))
        ]))

        elementos.append(tabla)

    elementos.append(Spacer(1, 25))

    elementos.append(
        Paragraph(
            "BOIX ERP | Documento de control interno",
            estilos["Normal"]
        )
    )

    documento.build(elementos)

    buffer.seek(0)
    return buffer.getvalue()

def generar_pdf_inventario():

    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Table,
        TableStyle, Spacer
    )
    from reportlab.lib.styles import (
        getSampleStyleSheet, ParagraphStyle
    )
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from xml.sax.saxutils import escape

    inventario = obtener_inventario()

    buffer = BytesIO()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=35,
        leftMargin=35,
        topMargin=45,
        bottomMargin=45
    )

    estilos = getSampleStyleSheet()

    estilos.add(ParagraphStyle(
        name="InventarioTitulo",
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=HexColor("#10243A"),
        spaceAfter=15
    ))

    estilos.add(ParagraphStyle(
        name="InventarioCelda",
        fontName="Helvetica",
        fontSize=8,
        leading=11
    ))

    elementos = [
        Paragraph(
            "BOIX | INFORME DE INVENTARIO",
            estilos["InventarioTitulo"]
        ),
        Paragraph(
            f"Fecha de emisión: {date.today():%d/%m/%Y}",
            estilos["Normal"]
        ),
        Spacer(1, 20)
    ]

    if inventario.empty:
        elementos.append(
            Paragraph(
                "No hay productos registrados.",
                estilos["Normal"]
            )
        )

    else:
        valor_total = (
            inventario["stock_actual"] *
            inventario["precio_unitario"]
        ).sum()

        elementos.append(
            Paragraph(
                f"Referencias registradas: {len(inventario)}",
                estilos["Normal"]
            )
        )

        elementos.append(
            Paragraph(
                f"Valor total del inventario: "
                f"{valor_total:,.2f} EUR",
                estilos["Normal"]
            )
        )

        elementos.append(Spacer(1, 20))

        datos = [[
            "Referencia",
            "Producto",
            "Stock",
            "Mínimo",
            "Valor"
        ]]

        for _, fila in inventario.iterrows():

            valor = (
                float(fila["stock_actual"]) *
                float(fila["precio_unitario"])
            )

            datos.append([
                Paragraph(
                    escape(str(fila["referencia"])),
                    estilos["InventarioCelda"]
                ),
                Paragraph(
                    escape(str(fila["producto"])),
                    estilos["InventarioCelda"]
                ),
                f"{float(fila['stock_actual']):g}",
                f"{float(fila['stock_minimo']):g}",
                f"{valor:,.2f} EUR"
            ])

        tabla = Table(
            datos,
            colWidths=[95, 180, 65, 65, 115],
            repeatRows=1,
            hAlign="LEFT"
        )

        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0),
             HexColor("#10243A")),
            ("TEXTCOLOR", (0, 0), (-1, 0),
             colors.white),
            ("FONTNAME", (0, 0), (-1, 0),
             "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, HexColor("#F4F7FB")]),
            ("LINEBELOW", (0, 0), (-1, -1),
             0.3, HexColor("#DCE3EB"))
        ]))

        elementos.append(tabla)

    elementos.append(Spacer(1, 25))

    elementos.append(
        Paragraph(
            "BOIX ERP | Documento de control interno",
            estilos["Normal"]
        )
    )

    documento.build(elementos)

    buffer.seek(0)
    return buffer.getvalue()

def generar_pdf_pedido(id_pedido):

    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Table,
        TableStyle, Spacer, KeepTogether
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from xml.sax.saxutils import escape

    cabecera, lineas = obtener_pedido_por_id(id_pedido)

    if cabecera.empty:
        raise ValueError("No se ha encontrado el pedido.")

    pedido = cabecera.iloc[0]

    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=45,
        bottomMargin=45
    )

    estilos = getSampleStyleSheet()

    estilos.add(ParagraphStyle(
        name="BoixTitulo",
        fontName="Helvetica-Bold",
        fontSize=25,
        textColor=HexColor("#10243A"),
        spaceAfter=15
    ))

    estilos.add(ParagraphStyle(
        name="BoixNormal",
        fontName="Helvetica",
        fontSize=10,
        leading=15
    ))

    estilos.add(ParagraphStyle(
        name="BoixDerecha",
        fontName="Helvetica-Bold",
        fontSize=12,
        alignment=TA_RIGHT,
        textColor=HexColor("#10243A")
    ))

    elementos = []

    elementos.append(
        Paragraph("BOIX | ORDEN DE COMPRA", estilos["BoixTitulo"])
    )

    elementos.append(
        Paragraph(
            f"<b>Referencia:</b> {escape(str(pedido['referencia']))}",
            estilos["BoixNormal"]
        )
    )

    elementos.append(
        Paragraph(
            f"<b>Proveedor:</b> {escape(str(pedido['proveedor']))}",
            estilos["BoixNormal"]
        )
    )

    elementos.append(
        Paragraph(
            f"<b>Fecha:</b> {escape(str(pedido['fecha_pedido']))}",
            estilos["BoixNormal"]
        )
    )

    elementos.append(
        Paragraph(
            f"<b>Estado:</b> {escape(str(pedido['estado']))}",
            estilos["BoixNormal"]
        )
    )

    elementos.append(Spacer(1, 25))

    datos = [[
        "Producto", "Cantidad", "Precio unit.", "Importe"
    ]]

    total = 0

    for _, linea in lineas.iterrows():

        importe = (
            float(linea["cantidad"]) *
            float(linea["precio_unitario"])
        )

        total += importe

        datos.append([
            Paragraph(
                escape(str(linea["producto"])),
                estilos["BoixNormal"]
            ),
            f"{float(linea['cantidad']):g}",
            f"{float(linea['precio_unitario']):,.2f} EUR",
            f"{importe:,.2f} EUR"
        ])

    tabla = Table(
        datos,
        colWidths=[225, 65, 100, 100],
        repeatRows=1,
        hAlign="LEFT"
    )

    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#10243A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4,
         HexColor("#DCE3EB")),
    ]))

    elementos.append(tabla)
    elementos.append(Spacer(1, 25))

    elementos.append(
        Paragraph(
            f"IMPORTE TOTAL: {total:,.2f} EUR",
            estilos["BoixDerecha"]
        )
    )

    elementos.append(Spacer(1, 30))

    elementos.append(
        Paragraph(
            "Documento de control interno generado por BOIX ERP. "
            "Los importes corresponden al pedido registrado.",
            estilos["BoixNormal"]
        )
    )

    documento.build(elementos)

    buffer.seek(0)
    return buffer.getvalue()

def generar_pdf_factura(factura):

    buffer = BytesIO()

    pdf = canvas.Canvas(buffer, pagesize=A4)
    ancho, alto = A4

    pdf.setTitle(str(factura["referencia"]))

    # CABECERA CORPORATIVA

    pdf.setFillColor(HexColor("#10243A"))
    pdf.rect(0, alto - 140, ancho, 140, fill=1, stroke=0)

    pdf.setFillColor(HexColor("#FFFFFF"))

    pdf.setFont("Helvetica-Bold", 32)
    pdf.drawString(45, alto - 55, "BOIX")

    pdf.setFont("Helvetica", 10)
    pdf.drawString(45, alto - 75, "GESTIÓN EMPRESARIAL")

    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawRightString(
        ancho - 45, alto - 55,
        str(factura["referencia"])
    )

    pdf.setFont("Helvetica", 10)
    pdf.drawRightString(
        ancho - 45, alto - 75,
        "REGISTRO DE FACTURA RECIBIDA"
    )

    # DATOS GENERALES

    pdf.setFillColor(HexColor("#10243A"))
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(45, alto - 180, "Datos de facturación")

    datos = [
        ("Proveedor", factura["proveedor"]),
        ("Número de factura", factura["numero_proveedor"]),
        ("Pedido asociado", factura["pedido"]),
        ("Fecha de emisión", factura["fecha_emision"]),
        ("Fecha de vencimiento", factura["fecha_vencimiento"]),
        ("Estado", factura["estado"]),
        ("Fecha de pago", factura["fecha_pago"] or "Sin registrar")
    ]

    y = alto - 215

    for etiqueta, valor in datos:

        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(45, y, etiqueta)

        pdf.setFont("Helvetica", 11)
        pdf.drawRightString(
            ancho - 45, y, str(valor)
        )

        pdf.setStrokeColor(HexColor("#DCE3EB"))
        pdf.line(45, y - 12, ancho - 45, y - 12)

        y -= 35

    # RESUMEN ECONÓMICO

    y -= 20

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(45, y, "Resumen económico")

    y -= 40

    importes = [
        ("Base imponible", factura["base_imponible"]),
        (f"IVA ({factura['iva']:g} %)", factura["cuota_iva"])
    ]

    for etiqueta, importe in importes:

        pdf.setFont("Helvetica", 12)
        pdf.drawString(45, y, etiqueta)

        pdf.drawRightString(
            ancho - 45, y, f"{importe:,.2f} EUR"
        )

        y -= 35

    # IMPORTE TOTAL
    y -= 20
    pdf.setFillColor(HexColor("#10243A"))
    pdf.roundRect(
        45, y - 20, ancho - 90, 55,
        8, fill=1, stroke=0
    )

    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.setFont("Helvetica-Bold", 14)

    pdf.drawString(60, y, "IMPORTE TOTAL")

    pdf.drawRightString(
        ancho - 60, y,
        f"{factura['importe_total']:,.2f} EUR"
    )

    # PIE DE PÁGINA

    pdf.setFillColor(HexColor("#7B8794"))
    pdf.setFont("Helvetica", 9)

    pdf.drawCentredString(
        ancho / 2, 55,
        "BOIX ERP | Sistema de gestión empresarial"
    )

    pdf.setFont("Helvetica", 8)

    pdf.drawCentredString(
        ancho / 2, 40,
        "Documento de control interno. No sustituye a la factura original."
    )

    pdf.showPage()
    pdf.save()

    buffer.seek(0)

    return buffer.getvalue()
def actualizar_estado_factura(id_factura, nuevo_estado):

    if nuevo_estado not in ["Pendiente", "Pagada"]:
        raise ValueError("Estado no válido.")

    conexion = conectar()

    try:
        with conexion:

            fecha_pago = (
                str(date.today())
                if nuevo_estado == "Pagada"
                else None
            )

            conexion.execute("""
                UPDATE facturas
                SET estado = ?, fecha_pago = ?
                WHERE id = ?
            """, (
                nuevo_estado,
                fecha_pago,
                id_factura
            ))

    finally:
        conexion.close()

def obtener_importe_total_pedidos():
    conexion = conectar()
    total = conexion.execute("""
        SELECT COALESCE(
            SUM(cantidad * precio_unitario), 0
        )
        FROM lineas_pedido
    """).fetchone()[0]
    conexion.close()
    return total
# ----------------------------------
# MENÚ LATERAL
# ----------------------------------


# ----------------------------------
# IDENTIDAD VISUAL Y NAVEGACIÓN
# ----------------------------------

RUTA_LOGO = Path(__file__).resolve().parent / "logo_boix.png"



st.markdown("""
<style>

/* Menú vertical BOIX */
section[data-testid="stSidebar"] [role="radiogroup"] {
    gap: 7px;
}

/* Opciones de navegación */
section[data-testid="stSidebar"] [role="radiogroup"] label {
    display: flex;
    align-items: center;
    border-radius: 9px;
    padding: 12px 14px;
    cursor: pointer;
    transition: background 0.2s ease;
}

/* Ocultar el indicador de radio */
section[data-testid="stSidebar"] [role="radiogroup"]
label input[type="radio"] {
    display: none !important;
}

section[data-testid="stSidebar"] [role="radiogroup"]
label [data-testid="stRadioButton"] {
    display: none !important;
}

section[data-testid="stSidebar"] [role="radiogroup"]
label [data-baseweb="radio"] > div:first-child {
    display: none !important;
}

/* Alternativa para el círculo SVG */
section[data-testid="stSidebar"] [role="radiogroup"]
label svg {
    display: none !important;
}

/* Nombres y símbolos */
section[data-testid="stSidebar"] [role="radiogroup"] label p {
    color: #FFFFFF !important;
    font-size: 18px !important;
    font-weight: 500;
    line-height: 1.5;
}

/* Efecto hover */
section[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    background: #203650;
}

/* Opción seleccionada */
section[data-testid="stSidebar"] [role="radiogroup"]
label:has(input:checked) {
    background: #285477;
}

section[data-testid="stSidebar"] [role="radiogroup"]
label:has(input:checked) p {
    font-weight: 700;
}

</style>
""", unsafe_allow_html=True)


st.markdown("""
<style>
/* Botones de navegación BOIX */
section[data-testid="stSidebar"] div.stButton > button[kind="secondary"] {
    background-color: #1B344D !important;
    color: #FFFFFF !important;
    border: 1px solid #304B65 !important;
    border-radius: 9px !important;
    min-height: 45px;
    font-size: 15px !important;
    font-weight: 600 !important;
}

/* Texto de los botones */
section[data-testid="stSidebar"] div.stButton > button[kind="secondary"] p {
    color: #FFFFFF !important;
}

/* Efecto al pasar el ratón */
section[data-testid="stSidebar"] div.stButton > button[kind="secondary"]:hover {
    background-color: #285477 !important;
    border-color: #4095C5 !important;
}

/* Botón seleccionado */
section[data-testid="stSidebar"] div.stButton > button[kind="primary"] {
    background-color: #168AC4 !important;
    color: #FFFFFF !important;
    border-radius: 9px !important;
    min-height: 45px;
    font-size: 15px !important;
    font-weight: 700 !important;
}

section[data-testid="stSidebar"] div.stButton > button[kind="primary"] p {
    color: #FFFFFF !important;
}
</style>
""", unsafe_allow_html=True)


with st.sidebar:

    st.image(
        str(RUTA_LOGO),
        use_container_width=True
    )

    st.markdown(
        """
        <div style="text-align:center; margin-top:-8px;">
            <p style="
                color:#FFFFFF;
                font-size:11px;
                font-weight:600;
                letter-spacing:2px;
                margin-bottom:4px;">
                GESTIÓN EMPRESARIAL
            </p>
            <p style="
                color:#FFFFFF;
font-size:13px;
font-weight:600;
                margin-top:0;">
                BOIX ERP
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.divider()

    st.markdown(
        """
        <p style="
            color:#color:#FFFFFF;
            font-size:11px;
            font-weight:700;
            letter-spacing:1.5px;
            margin-bottom:8px;">
            MENÚ PRINCIPAL
        </p>
        """,
        unsafe_allow_html=True
    )

   


    opciones_menu = [
        ("Dashboard", ":material/dashboard:"),
        ("Clientes", ":material/groups:"),
        ("Proveedores", ":material/factory:"),
        ("Pedidos", ":material/inventory_2:"),
        ("Inventario", ":material/warehouse:"),
        ("Facturación", ":material/receipt_long:"),
        ("Incidencias", ":material/report_problem:")
    ]

    if "seccion_actual" not in st.session_state:
        st.session_state.seccion_actual = "Dashboard"

    for nombre, icono in opciones_menu:

        if st.button(
            nombre,
            icon=icono,
            key=f"menu_{nombre}",
            use_container_width=True,
            type=(
                "primary"
                if st.session_state.seccion_actual == nombre
                else "secondary"
            )
        ):
            st.session_state.seccion_actual = nombre
            st.rerun()

    seccion = st.session_state.seccion_actual




    st.divider()

    st.markdown(
        """
        <div style="text-align:center;">
            <p style="
                color:#FFFFFF;
                font-size:12px;
                font-weight:700;
                margin-bottom:3px;">
                BOIX ERP
            </p>
            <p style="
                color:#7B8794;
                font-size:10px;
                margin-top:0;">
                SISTEMA DE GESTIÓN · V1.0
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )


# ----------------------------------
# DASHBOARD
# ----------------------------------


# ----------------------------------
# DASHBOARD
# ----------------------------------

if seccion == "Dashboard":


    # CABECERA CORPORATIVA BOIX
    with st.container(border=True):
        st.caption("BOIX ERP · GESTIÓN EMPRESARIAL")
        st.title("Panel de control")
        st.write(
            "Supervisión de operaciones, pedidos y actividad administrativa."
        )


    # DATOS
    clientes = obtener_clientes()
    proveedores = obtener_proveedores()
    pedidos = obtener_pedidos()

    total_clientes = len(clientes)
    total_proveedores = len(proveedores)
    total_pedidos = obtener_total_pedidos()
    importe_total = obtener_importe_total_pedidos()

    st.download_button(
        label="Descargar informe de actividad",
        data=generar_pdf_dashboard(),
        file_name=f"BOIX_Dashboard_{date.today()}.pdf",
        mime="application/pdf",
        icon=":material/download:",
        type="primary",
        use_container_width=True
    )
    

    st.divider()


    # INDICADORES PRINCIPALES
    st.subheader("Resumen general")

    col1, col2, col3, col4 = st.columns(4, gap="small")

    with col1:
        with st.container(border=True):
            st.caption("CLIENTES")
            st.metric(
                label="Clientes registrados",
                value=total_clientes
            )

    with col2:
        with st.container(border=True):
            st.caption("PROVEEDORES")
            st.metric(
                label="Proveedores registrados",
                value=total_proveedores
            )

    with col3:
        with st.container(border=True):
            st.caption("PEDIDOS")
            st.metric(
                label="Pedidos registrados",
                value=total_pedidos
            )

    with col4:
        with st.container(border=True):
            st.caption("VOLUMEN ECONÓMICO")
            st.metric(
                label="Importe acumulado",
                value=f"{importe_total:,.2f} €"
            )



    st.divider()


     # SEGUIMIENTO DE PEDIDOS
    

    st.subheader("Seguimiento de pedidos")

    estados = [
        "Pendiente",
        "En preparación",
        "Enviado",
        "Entregado",
        "Cancelado"
    ]

    conteo_estados = (
        pedidos["estado"].value_counts()
        if not pedidos.empty
        else pd.Series(dtype=int)
    )

    columnas_estado = st.columns(5)

    iconos_estado = {
        "Pendiente": "🕒",
        "En preparación": "⚙️",
        "Enviado": "🚚",
        "Entregado": "✅",
        "Cancelado": "❌"
    }

    for columna, estado in zip(columnas_estado, estados):

        cantidad = int(conteo_estados.get(estado, 0))

        with columna:
            with st.container(border=True):
                st.markdown(
                    f"### {iconos_estado[estado]}"
                )
                st.metric(
                    label=estado,
                    value=cantidad
                )

    st.divider()


    # DISTRIBUCIÓN DE PEDIDOS
    
    # DISTRIBUCIÓN DE PEDIDOS
    st.subheader("Análisis de pedidos")

    col1, col2 = st.columns([2, 1])

    with col1:

        st.markdown("#### Pedidos por estado")

        if not pedidos.empty:

            datos_grafico = pd.DataFrame({
                "Estado": estados,
                "Número de pedidos": [
                    int(conteo_estados.get(estado, 0))
                    for estado in estados
                ]
            })

         
        
            grafico = alt.Chart(datos_grafico).mark_bar(
                color="#315B82"
            ).encode(
                x=alt.X(
                    "Estado:N",
                    sort=None,
                    axis=alt.Axis(
                        labelAngle=0,
                        labelFontSize=11,
                        labelLimit=150,
                        title=None
                    )
                ),
                y=alt.Y(
                    "Número de pedidos:Q",
                    title="Número de pedidos"
                ),
                tooltip=[
                    "Estado:N",
                    "Número de pedidos:Q"
                ]
            ).properties(
                height=300
            )

            st.altair_chart(
                grafico,
                use_container_width=True
            )



        else:
            st.info("Todavía no hay pedidos para representar.")

    with col2:

        st.markdown("#### Resumen")

        pedidos_pendientes = int(
            conteo_estados.get("Pendiente", 0)
        )

        pedidos_entregados = int(
            conteo_estados.get("Entregado", 0)
        )

        pedidos_cancelados = int(
            conteo_estados.get("Cancelado", 0)
        )

        st.metric("Pendientes", pedidos_pendientes)
        st.metric("Entregados", pedidos_entregados)
        st.metric("Cancelados", pedidos_cancelados)

    st.divider()

    # ACTIVIDAD RECIENTE
    
    # ACTIVIDAD RECIENTE
    st.subheader("Actividad reciente")
    st.caption("Últimos cinco pedidos registrados en BOIX.")

    conexion = conectar()

    actividad = pd.read_sql_query("""
        SELECT
            p.referencia AS Referencia,
            pr.empresa AS Proveedor,
            p.fecha_pedido AS Fecha,
            p.estado AS Estado,
            COALESCE(
                SUM(lp.cantidad * lp.precio_unitario), 0
            ) AS Importe
        FROM pedidos p
        LEFT JOIN proveedores pr
            ON pr.id = p.proveedor_id
        LEFT JOIN lineas_pedido lp
            ON lp.pedido_id = p.id
        GROUP BY p.id
        ORDER BY p.id DESC
        LIMIT 5
    """, conexion)

    conexion.close()

    if not actividad.empty:

        actividad["Importe"] = actividad["Importe"].map(
            lambda x: f"{x:,.2f} €"
        )

        actividad["Estado"] = actividad["Estado"].fillna(
            "Sin estado"
        )

        st.dataframe(
            actividad,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Referencia": st.column_config.TextColumn(
                    "Referencia",
                    width="medium"
                ),
                "Proveedor": st.column_config.TextColumn(
                    "Proveedor",
                    width="large"
                ),
                "Fecha": st.column_config.DateColumn(
                    "Fecha",
                    format="DD/MM/YYYY"
                ),
                "Estado": st.column_config.TextColumn(
                    "Estado",
                    width="medium"
                ),
                "Importe": st.column_config.TextColumn(
                    "Importe",
                    width="medium"
                )
            }
        )

    else:
        st.info("Todavía no hay actividad registrada.")

    st.divider()

    st.caption("BOIX ERP · Panel de control")

# ----------------------------------
# CLIENTES
# ----------------------------------

elif seccion == "Clientes":

    st.title("Gestión de clientes")
    st.write("Directorio y mantenimiento de clientes.")

    st.download_button(
        label="📄 Descargar directorio de clientes (PDF)",
        data=generar_pdf_clientes(),
        file_name=f"BOIX_Clientes_{date.today()}.pdf",
        mime="application/pdf",
        use_container_width=True
    )

    pestaña1, pestaña2, pestaña3 = st.tabs([
        "Directorio",
        "Nuevo cliente",
        "Editar / Eliminar"
    ])

    clientes = obtener_clientes()

    # DIRECTORIO
    with pestaña1:

        st.subheader("Directorio de clientes")

        busqueda = st.text_input(
            "Buscar por empresa, nombre o NIF",
            placeholder="Escribe para buscar..."
        )

        if not clientes.empty:

            filtrados = clientes.copy()

            if busqueda:
                columnas = ["empresa", "nombre", "nif"]
                mascara = filtrados[columnas].fillna("").apply(
                    lambda columna: columna.str.contains(
                        busqueda,
                        case=False,
                        regex=False
                    )
                ).any(axis=1)

                filtrados = filtrados[mascara]

            st.caption(f"Resultados: {len(filtrados)}")

            st.dataframe(
                filtrados,
                use_container_width=True,
                hide_index=True
            )

        else:
            st.info("Todavía no hay clientes registrados.")

    # NUEVO CLIENTE
    with pestaña2:

        st.subheader("Registrar nuevo cliente")

        with st.form("formulario_cliente", clear_on_submit=True):

            empresa = st.text_input("Empresa *")
            nombre = st.text_input("Persona de contacto *")
            nif = st.text_input("NIF / CIF")
            email = st.text_input("Correo electrónico")
            telefono = st.text_input("Teléfono")

            guardar = st.form_submit_button(
                "Guardar cliente",
                use_container_width=True
            )

            if guardar:

                if not empresa.strip() or not nombre.strip():
                    st.error("Empresa y persona de contacto son obligatorios.")

                else:
                    guardar_cliente(
                        empresa.strip(),
                        nombre.strip(),
                        nif.strip(),
                        email.strip(),
                        telefono.strip()
                    )

                    st.success("Cliente registrado correctamente.")
                    st.rerun()

    # EDITAR / ELIMINAR
    with pestaña3:

        st.subheader("Mantenimiento de clientes")

        if clientes.empty:

            st.info("No hay clientes para modificar.")

        else:

            opciones = {
                f"{fila['empresa']} — {fila['nombre']} (ID {fila['id']})":
                int(fila["id"])
                for _, fila in clientes.iterrows()
            }

            seleccion = st.selectbox(
                "Selecciona un cliente",
                list(opciones.keys())
            )

            id_seleccionado = opciones[seleccion]

            cliente = clientes[
                clientes["id"] == id_seleccionado
            ].iloc[0]

            st.divider()

            with st.form("formulario_edicion"):

                nueva_empresa = st.text_input(
                    "Empresa",
                    value=cliente["empresa"]
                )

                nuevo_nombre = st.text_input(
                    "Persona de contacto",
                    value=cliente["nombre"]
                )

                nuevo_nif = st.text_input(
                    "NIF / CIF",
                    value=cliente["nif"] or ""
                )

                nuevo_email = st.text_input(
                    "Correo electrónico",
                    value=cliente["email"] or ""
                )

                nuevo_telefono = st.text_input(
                    "Teléfono",
                    value=cliente["telefono"] or ""
                )

                actualizar = st.form_submit_button(
                    "Guardar cambios",
                    use_container_width=True
                )

                if actualizar:

                    if not nueva_empresa.strip() or not nuevo_nombre.strip():
                        st.error("Empresa y contacto son obligatorios.")

                    else:
                        actualizar_cliente(
                            id_seleccionado,
                            nueva_empresa.strip(),
                            nuevo_nombre.strip(),
                            nuevo_nif.strip(),
                            nuevo_email.strip(),
                            nuevo_telefono.strip()
                        )

                        st.success("Cliente actualizado correctamente.")
                        st.rerun()

            st.divider()

            st.warning(
                "La eliminación es permanente. Comprueba el cliente antes de continuar."
            )

            confirmar = st.checkbox(
                "Confirmo que quiero eliminar este cliente."
            )

            if st.button(
                "Eliminar cliente",
                type="secondary",
                disabled=not confirmar
            ):
                eliminar_cliente(id_seleccionado)
                st.success("Cliente eliminado.")
                st.rerun()

# ----------------------------------

elif seccion == "Proveedores":

    st.title("Gestión de proveedores")
    st.write("Directorio y gestión de proveedores de BOIX.")

    st.download_button(
        label="📄 Descargar directorio de proveedores (PDF)",
        data=generar_pdf_proveedores(),
        file_name=f"BOIX_Proveedores_{date.today()}.pdf",
        mime="application/pdf",
        use_container_width=True
    )

    pestaña1, pestaña2, pestaña3 = st.tabs([
    "Directorio",
    "Nuevo proveedor",
    "Editar / eliminar"
])

    proveedores = obtener_proveedores()

    with pestaña1:
        st.subheader("Directorio de proveedores")

        busqueda = st.text_input(
            "Buscar proveedor",
            placeholder="Empresa, contacto o CIF..."
        )

        if not proveedores.empty:
            filtrados = proveedores.copy()

            if busqueda:
                columnas = ["empresa", "contacto", "nif"]
                mascara = filtrados[columnas].fillna("").apply(
                    lambda columna: columna.str.contains(
                        busqueda, case=False, regex=False
                    )
                ).any(axis=1)

                filtrados = filtrados[mascara]

            st.caption(f"Proveedores encontrados: {len(filtrados)}")

            st.dataframe(
                filtrados,
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Todavía no hay proveedores registrados.")

    with pestaña2:
        st.subheader("Registrar proveedor")

        with st.form("formulario_proveedor", clear_on_submit=True):

            empresa = st.text_input("Empresa *")
            contacto = st.text_input("Persona de contacto *")
            nif = st.text_input("CIF / NIF")
            email = st.text_input("Correo electrónico")
            telefono = st.text_input("Teléfono")
            direccion = st.text_input("Dirección")

            categoria = st.selectbox(
                "Categoría de suministro",
                [
                    "Material industrial",
                    "Componentes",
                    "Logística y transporte",
                    "Servicios",
                    "Mantenimiento",
                    "Otros"
                ]
            )

            guardar = st.form_submit_button(
                "Guardar proveedor",
                use_container_width=True
            )

            if guardar:
                if not empresa.strip() or not contacto.strip():
                    st.error("Empresa y contacto son obligatorios.")
                else:
                    guardar_proveedor(
                        empresa.strip(),
                        contacto.strip(),
                        nif.strip(),
                        email.strip(),
                        telefono.strip(),
                        direccion.strip(),
                        categoria
                    )

                    st.success("Proveedor registrado correctamente.")
                    st.rerun()

    with pestaña3:
        st.subheader("Mantenimiento de proveedores")

        if not proveedores.empty:

            ids = proveedores["id"].tolist()

            id_seleccionado = st.selectbox(
                "Seleccionar proveedor",
                ids,
                format_func=lambda x: (
                    f"{proveedores.loc[proveedores['id'] == x, 'empresa'].iloc[0]} "
                    f"(ID: {x})"
                )
            )

            proveedor = proveedores[
                proveedores["id"] == id_seleccionado
            ].iloc[0]

            st.divider()
            st.write(f"**Editando:** {proveedor['empresa']}")

            with st.form("editar_proveedor"):

                empresa_edit = st.text_input(
                    "Empresa",
                    value=proveedor["empresa"] or ""
                )

                contacto_edit = st.text_input(
                    "Contacto",
                    value=proveedor["contacto"] or ""
                )

                nif_edit = st.text_input(
                    "CIF / NIF",
                    value=proveedor["nif"] or ""
                )

                email_edit = st.text_input(
                    "Correo electrónico",
                    value=proveedor["email"] or ""
                )

                telefono_edit = st.text_input(
                    "Teléfono",
                    value=proveedor["telefono"] or ""
                )

                direccion_edit = st.text_input(
                    "Dirección",
                    value=proveedor["direccion"] or ""
                )

                categorias = [
                    "Material industrial",
                    "Componentes",
                    "Logística y transporte",
                    "Servicios",
                    "Mantenimiento",
                    "Otros"
                ]

                categoria_actual = proveedor["categoria"]

                indice = (
                    categorias.index(categoria_actual)
                    if categoria_actual in categorias else 5
                )

                categoria_edit = st.selectbox(
                    "Categoría",
                    categorias,
                    index=indice
                )

                actualizar = st.form_submit_button(
                    "Guardar cambios",
                    use_container_width=True
                )

                if actualizar:
                    if not empresa_edit.strip() or not contacto_edit.strip():
                        st.error("Empresa y contacto son obligatorios.")
                    else:
                        actualizar_proveedor(
                            int(id_seleccionado),
                            empresa_edit.strip(),
                            contacto_edit.strip(),
                            nif_edit.strip(),
                            email_edit.strip(),
                            telefono_edit.strip(),
                            direccion_edit.strip(),
                            categoria_edit
                        )

                        st.success("Proveedor actualizado correctamente.")
                        st.rerun()

            st.divider()

            st.subheader("Eliminar proveedor")

            confirmar = st.checkbox(
                f"Confirmo que quiero eliminar a {proveedor['empresa']}"
            )

            if st.button(
                "Eliminar proveedor",
                type="secondary",
                disabled=not confirmar
            ):
                eliminar_proveedor(int(id_seleccionado))
                st.success("Proveedor eliminado correctamente.")
                st.rerun()

        else:
            st.info("No hay proveedores para gestionar.")


# ----------------------------------
# PEDIDOS
# ----------------------------------


elif seccion == "Pedidos":

    st.title("Gestión de pedidos")
    st.write("Registro, seguimiento y consulta de pedidos a proveedores.")

    pestaña1, pestaña2, pestaña3 = st.tabs([
        "Directorio de pedidos",
        "Nuevo pedido",
        "Editar pedido"
    ])

    pedidos = obtener_pedidos()
    proveedores = obtener_proveedores()


    with pestaña1:
        st.subheader("Directorio de pedidos")

        if pedidos.empty:
            st.info("Todavía no hay pedidos registrados.")
        else:
            filtro_estado = st.selectbox(
                "Filtrar por estado",
                ["Todos"] + sorted(pedidos["estado"].dropna().unique().tolist())
            )
            pedidos_filtrados = pedidos.copy()
            if filtro_estado != "Todos":
                pedidos_filtrados = pedidos_filtrados[
                    pedidos_filtrados["estado"] == filtro_estado
                ]

            st.caption(f"Pedidos encontrados: {len(pedidos_filtrados)}")
            st.dataframe(
                pedidos_filtrados,
                use_container_width=True,
                hide_index=True
            )

            st.divider()
            st.subheader("Actualizar estado de pedido")

            pedidos_opciones = {
                f"{fila['referencia']} · {fila['proveedor']} · {fila['estado']}": int(fila["id"])
                for _, fila in pedidos.iterrows()
            }
            pedido_seleccionado = st.selectbox(
                "Selecciona un pedido",
                list(pedidos_opciones.keys()),
                key="pedido_estado_selector"
            )
            id_pedido_seleccionado = pedidos_opciones[pedido_seleccionado]
            estado_actual = pedidos.loc[
                pedidos["id"] == id_pedido_seleccionado, "estado"
            ].iloc[0]

            estados = ["Pendiente", "En preparación", "Enviado", "Entregado", "Cancelado"]
            nuevo_estado = st.selectbox(
                "Nuevo estado",
                estados,
                index=estados.index(estado_actual) if estado_actual in estados else 0,
                key="pedido_nuevo_estado"
            )

       
            if st.button("Actualizar estado", use_container_width=True):
                try:
                    actualizar_estado_pedido(
                        id_pedido_seleccionado,
                        nuevo_estado
                    )

                    if nuevo_estado == "Entregado":
                        st.success(
                            "Pedido entregado. Inventario actualizado."
                        )
                    else:
                        st.success("Estado actualizado correctamente.")

                    st.rerun()

                except ValueError as error:
                    st.error(str(error))

            st.divider()
            st.subheader("Detalle de pedido")
            pedido_detalle = st.selectbox(
                "Consultar referencia",
                pedidos["referencia"].tolist(),
                key="pedido_detalle_selector"
            )
            id_detalle = int(pedidos.loc[
                pedidos["referencia"] == pedido_detalle, "id"
            ].iloc[0])
            cabecera, lineas = obtener_pedido_por_id(id_detalle)

            if not cabecera.empty:
                registro = cabecera.iloc[0]
                st.write(f"**Proveedor:** {registro['proveedor']}")
                st.write(f"**Fecha del pedido:** {registro['fecha_pedido']}")
                st.write(f"**Estado:** {registro['estado']}")
                if registro["observaciones"]:
                    st.write(f"**Observaciones:** {registro['observaciones']}")

            if not lineas.empty:
                lineas = lineas.copy()
                lineas["importe"] = lineas["cantidad"] * lineas["precio_unitario"]
                st.dataframe(lineas, use_container_width=True, hide_index=True)
                st.metric("Importe del pedido", f"{lineas['importe'].sum():,.2f} €")

                st.download_button(
                    "📄 Descargar pedido en PDF",
                    data=generar_pdf_pedido(id_detalle),
                    file_name=f"{pedido_detalle}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="descargar_pdf_pedido"
                )

 
    with pestaña2:
        st.subheader("Registrar nuevo pedido")

        if proveedores.empty:
            st.warning("Primero registra al menos un proveedor en el módulo Proveedores.")
        else:
            proveedor_opciones = {
                f"{fila['empresa']} (ID {int(fila['id'])})": int(fila["id"])
                for _, fila in proveedores.iterrows()
            }

            with st.form("form_nuevo_pedido", clear_on_submit=True):
                referencia = generar_referencia_pedido()
                st.text_input(
                    "Referencia automática",
                    value=referencia,
                    disabled=True
                )

                proveedor_nombre = st.selectbox("Proveedor *", list(proveedor_opciones.keys()))
                fecha_pedido = st.date_input("Fecha de pedido", value=date.today())
                fecha_entrega = st.date_input("Fecha prevista de entrega (opcional)", value=None)

                inventario_pedidos = obtener_inventario()

                opciones_inventario = {
                    "Introducir producto manualmente": None
                }

                for _, fila in inventario_pedidos.iterrows():
                    opciones_inventario[
                        f"{fila['referencia']} · {fila['producto']}"
                    ] = int(fila["id"])

                seleccion_producto = st.selectbox(
                    "Producto del inventario",
                    list(opciones_inventario.keys())
                )

                producto_id = opciones_inventario[seleccion_producto]

                producto_manual = st.text_input(
                    "Descripción (solo para productos manuales)"
                )

                if producto_id is not None:
                    registro_producto = inventario_pedidos[
                        inventario_pedidos["id"] == producto_id
                    ].iloc[0]

                    producto = registro_producto["producto"]
                else:
                    producto = producto_manual
                cantidad = st.number_input("Cantidad *", min_value=0.01, value=1.0, step=1.0)
                precio_unitario = st.number_input("Precio unitario (€) *", min_value=0.0, value=0.0, step=0.5)
                estado = st.selectbox("Estado inicial", ["Pendiente", "En preparación", "Enviado", "Entregado", "Cancelado"])
                observaciones = st.text_area("Observaciones")

                importe_estimado = cantidad * precio_unitario
                st.caption(f"Importe calculado: {importe_estimado:,.2f} €")

                crear = st.form_submit_button("Guardar pedido", use_container_width=True)

                if crear:
                    if not producto.strip():
                        st.error("La descripción del producto es obligatoria.")
                    else:
                        try:
                        
                            guardar_pedido(
                                referencia,
                                proveedor_opciones[proveedor_nombre],
                                fecha_pedido,
                                fecha_entrega,
                                estado,
                                observaciones.strip(),
                                producto.strip(),
                                cantidad,
                                precio_unitario,
                                producto_id
                            )

                            st.success("Pedido guardado correctamente.")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Ya existe un pedido con esa referencia. Inténtalo de nuevo.")



    with pestaña3:
        st.subheader("Editar pedido existente")

        if pedidos.empty:
            st.info("No hay pedidos disponibles para editar.")
        else:
            pedidos_opciones = {
                f"{fila['referencia']} · {fila['proveedor']}": int(fila["id"])
                for _, fila in pedidos.iterrows()
            }

            pedido_seleccionado = st.selectbox(
                "Selecciona el pedido que quieres editar",
                list(pedidos_opciones.keys()),
                key="pedido_editar_selector"
            )

            id_editar = pedidos_opciones[pedido_seleccionado]
            cabecera, lineas = obtener_pedido_por_id(id_editar)

            if not cabecera.empty and not lineas.empty:
                registro = cabecera.iloc[0]
                linea = lineas.iloc[0]

                with st.form("form_editar_pedido"):
                    proveedor_actual = int(registro["proveedor_id"])
                    proveedor_ids = list(proveedor_opciones.values())
                    indice_proveedor = proveedor_ids.index(proveedor_actual)

                    proveedor_editar = st.selectbox(
                        "Proveedor",
                        list(proveedor_opciones.keys()),
                        index=indice_proveedor
                    )

                    fecha_pedido_editar = st.date_input(
                        "Fecha de pedido",
                        value=pd.to_datetime(registro["fecha_pedido"]).date()
                    )

                    fecha_entrega_actual = (
                        pd.to_datetime(registro["fecha_entrega"]).date()
                        if pd.notna(registro["fecha_entrega"])
                        else None
                    )

                    fecha_entrega_editar = st.date_input(
                        "Fecha prevista de entrega",
                        value=fecha_entrega_actual
                    )

                   
                    producto_vinculado = pd.notna(
                        linea["producto_id"]
                    )

                    producto_editar = st.text_input(
                        "Producto",
                        value=str(linea["producto"]),
                        disabled=producto_vinculado
                    )

                    if producto_vinculado:
                        st.caption(
                            "Producto vinculado al inventario. "
                            "No se puede modificar su descripción."
                        )


                    cantidad_editar = st.number_input(
                        "Cantidad",
                        min_value=0.01,
                        value=float(linea["cantidad"]),
                        step=1.0
                    )

                    precio_editar = st.number_input(
                        "Precio unitario (€)",
                        min_value=0.0,
                        value=float(linea["precio_unitario"]),
                        step=0.5
                    )

                    estado_editar = st.selectbox(
                        "Estado",
                        ["Pendiente", "En preparación", "Enviado", "Entregado", "Cancelado"],
                        index=["Pendiente", "En preparación", "Enviado", "Entregado", "Cancelado"].index(registro["estado"])
                    )

                    observaciones_editar = st.text_area(
                        "Observaciones",
                        value=registro["observaciones"] or ""
                    )

                    guardar_cambios = st.form_submit_button(
                        "Guardar cambios",
                        use_container_width=True
                    )

                    if guardar_cambios:
                        if not producto_editar.strip():
                            st.error("El producto no puede estar vacío.")
                     
                        else:
                            try:
                                actualizar_pedido(
                                    id_editar,
                                    proveedor_opciones[proveedor_editar],
                                    fecha_pedido_editar,
                                    fecha_entrega_editar,
                                    estado_editar,
                                    observaciones_editar.strip(),
                                    producto_editar.strip(),
                                    cantidad_editar,
                                    precio_editar
                                )
                                st.success("Pedido actualizado correctamente.")
                                st.rerun()

                            except ValueError as error:
                                st.error(str(error))

                st.divider()
                st.subheader("Eliminar pedido")

                confirmar_eliminacion = st.checkbox(
                    "Confirmo que quiero eliminar este pedido",
                    key="confirmar_eliminar_pedido"
                )

           
                st.markdown("""
/* Iconos del menú más grandes */
section[data-testid="stSidebar"] div.stButton button span[data-testid="stIconMaterial"] {
    font-size: 23px !important;
}

/* Altura y separación de los botones */
section[data-testid="stSidebar"] div.stButton button {
    min-height: 48px !important;
    gap: 12px !important;
}
<style>
.st-key-boton_eliminar_pedido button {
    background-color: #C62828 !important;
    color: white !important;
    border: 1px solid #C62828 !important;
}

.st-key-boton_eliminar_pedido button:hover {
    background-color: #A61F1F !important;
    color: white !important;
    border-color: #A61F1F !important;
}
</style>
                """, unsafe_allow_html=True)

                if st.button(
                    "Eliminar pedido",
                    type="primary",
                    use_container_width=True,
                    key="boton_eliminar_pedido"
                ):

             
                    if confirmar_eliminacion:
                        try:
                            eliminar_pedido(id_editar)
                            st.success("Pedido eliminado correctamente.")
                            st.rerun()

                        except ValueError as error:
                            st.error(str(error))

                    else:
                        st.warning(
                            "Debes confirmar la eliminación antes de continuar."
                        )


# ----------------------------------
# INVENTARIO
# ----------------------------------

elif seccion == "Inventario":

    st.caption("BOIX ERP · GESTIÓN DE ALMACÉN")
    st.title("Gestión de inventario")
    st.write("Control de existencias y materiales industriales.")

    inventario = obtener_inventario()

    st.download_button(
        label="📄 Descargar informe de inventario (PDF)",
        data=generar_pdf_inventario(),
        file_name=f"BOIX_Inventario_{date.today()}.pdf",
        mime="application/pdf",
        use_container_width=True
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Referencias", len(inventario))

    with col2:
        st.metric(
            "Unidades en stock",
            f"{inventario['stock_actual'].sum():g}"
        )

    with col3:
        stock_bajo = inventario[
            (inventario["stock_actual"] <= inventario["stock_minimo"]) &
            (inventario["stock_actual"] > 0)
        ]
        st.metric("Stock bajo", len(stock_bajo))

    with col4:
        agotados = inventario[inventario["stock_actual"] == 0]
        st.metric("Agotados", len(agotados))

    st.divider()

    pestaña1, pestaña2, pestaña3, pestaña4, pestaña5 = st.tabs([
        "Directorio de inventario",
        "Nuevo producto",
        "Editar / Eliminar",
        "Movimientos",
        "Historial"
    ])
    with pestaña1:

        st.subheader("Control de existencias")

        if inventario.empty:
            st.info("Todavía no hay productos registrados.")


        else:

            datos = inventario.copy()

            datos["estado"] = datos.apply(
                lambda fila: (
                    "🔴 Agotado"
                    if fila["stock_actual"] == 0
                    else "🟠 Stock bajo"
                    if fila["stock_actual"] <= fila["stock_minimo"]
                    else "🟢 Disponible"
                ),
                axis=1
            )

            datos["valor_stock"] = (
                datos["stock_actual"] *
                datos["precio_unitario"]
            )

            col1, col2, col3 = st.columns([2, 1, 1])

            with col1:
                busqueda = st.text_input(
                    "Buscar producto",
                    placeholder="Referencia o nombre..."
                )

            with col2:
                filtro_categoria = st.selectbox(
                    "Categoría",
                    ["Todas"] + sorted(
                        datos["categoria"].dropna().unique().tolist()
                    )
                )

            with col3:
                filtro_estado = st.selectbox(
                    "Estado del stock",
                    [
                        "Todos",
                        "🟢 Disponible",
                        "🟠 Stock bajo",
                        "🔴 Agotado"
                    ]
                )

            if busqueda:
                datos = datos[
                    datos["referencia"].str.contains(
                        busqueda, case=False, regex=False
                    ) |
                    datos["producto"].str.contains(
                        busqueda, case=False, regex=False
                    )
                ]

            if filtro_categoria != "Todas":
                datos = datos[
                    datos["categoria"] == filtro_categoria
                ]

            if filtro_estado != "Todos":
                datos = datos[
                    datos["estado"] == filtro_estado
                ]

            st.caption(f"Productos encontrados: {len(datos)}")

            st.dataframe(
                datos[[
                    "referencia",
                    "producto",
                    "categoria",
                    "proveedor",
                    "ubicacion",
                    "stock_actual",
                    "stock_minimo",
                    "precio_unitario",
                    "valor_stock",
                    "estado"
                ]],
                column_config={
                    "referencia": "Referencia",
                    "producto": "Producto",
                    "categoria": "Categoría",
                    "proveedor": "Proveedor",
                    "ubicacion": "Ubicación",
                    "stock_actual": "Existencias",
                    "stock_minimo": "Stock mínimo",
                    "precio_unitario": st.column_config.NumberColumn(
                        "Precio unitario",
                        format="%.2f €"
                    ),
                    "valor_stock": st.column_config.NumberColumn(
                        "Valor del stock",
                        format="%.2f €"
                    ),
                    "estado": "Estado"
                },
                use_container_width=True,
                hide_index=True
            )


    with pestaña2:

        st.subheader("Registrar nuevo producto")

        proveedores = obtener_proveedores()

        opciones = {"Sin proveedor asignado": None}

        for _, fila in proveedores.iterrows():
            opciones[
                f"{fila['empresa']} (ID {fila['id']})"
            ] = int(fila["id"])

        with st.form("formulario_inventario"):

            col1, col2 = st.columns(2)

            with col1:
                referencia = st.text_input("Referencia *")
                producto = st.text_input("Nombre del producto *")

                categoria = st.selectbox(
                    "Categoría",
                    [
                        "Material industrial",
                        "Componentes eléctricos",
                        "Componentes mecánicos",
                        "Herramientas",
                        "Repuestos",
                        "Otros"
                    ]
                )

                proveedor = st.selectbox(
                    "Proveedor",
                    list(opciones.keys())
                )

            with col2:
                ubicacion = st.text_input("Ubicación en almacén")

                stock_actual = st.number_input(
                    "Stock actual",
                    min_value=0.0,
                    step=1.0
                )

                stock_minimo = st.number_input(
                    "Stock mínimo",
                    min_value=0.0,
                    step=1.0
                )

                precio_unitario = st.number_input(
                    "Precio unitario (€)",
                    min_value=0.0,
                    step=0.5
                )

            guardar = st.form_submit_button(
                "Registrar producto",
                use_container_width=True
            )

            if guardar:

                if not referencia.strip() or not producto.strip():
                    st.error("Referencia y producto son obligatorios.")

                else:
                    try:
                        guardar_producto(
                            referencia.strip().upper(),
                            producto.strip(),
                            categoria,
                            opciones[proveedor],
                            ubicacion.strip(),
                            stock_actual,
                            stock_minimo,
                            precio_unitario
                        )

                        st.success("Producto registrado correctamente.")
                        st.rerun()

                    except sqlite3.IntegrityError:
                        st.error("La referencia ya existe.")


    with pestaña3:

        st.subheader("Mantenimiento de inventario")

        if inventario.empty:
            st.info("No hay productos para modificar.")

        else:

            opciones_productos = {
                f"{fila['referencia']} · {fila['producto']}":
                int(fila["id"])
                for _, fila in inventario.iterrows()
            }

            seleccion = st.selectbox(
                "Seleccionar producto",
                list(opciones_productos.keys()),
                key="inventario_editar"
            )

            id_producto = opciones_productos[seleccion]

            registro = inventario[
                inventario["id"] == id_producto
            ].iloc[0]

            proveedores = obtener_proveedores()

            opciones_proveedores = {
                "Sin proveedor asignado": None
            }

            for _, fila in proveedores.iterrows():
                opciones_proveedores[
                    f"{fila['empresa']} (ID {fila['id']})"
                ] = int(fila["id"])

            categorias = [
                "Material industrial",
                "Componentes eléctricos",
                "Componentes mecánicos",
                "Herramientas",
                "Repuestos",
                "Otros"
            ]

            proveedor_actual = next(
                (
                    nombre
                    for nombre, identificador
                    in opciones_proveedores.items()
                    if identificador == registro["proveedor_id"]
                ),
                "Sin proveedor asignado"
            )

            st.divider()

            with st.form(
                f"editar_producto_{id_producto}"
            ):

                col1, col2 = st.columns(2)

                with col1:

                    referencia_edit = st.text_input(
                        "Referencia",
                        value=registro["referencia"]
                    )

                    producto_edit = st.text_input(
                        "Producto",
                        value=registro["producto"]
                    )

                    categoria_edit = st.selectbox(
                        "Categoría",
                        categorias,
                        index=categorias.index(
                            registro["categoria"]
                        ) if registro["categoria"]
                        in categorias else 5
                    )

                    proveedor_edit = st.selectbox(
                        "Proveedor",
                        list(opciones_proveedores.keys()),
                        index=list(
                            opciones_proveedores.keys()
                        ).index(proveedor_actual)
                    )

                with col2:

                    ubicacion_edit = st.text_input(
                        "Ubicación",
                        value=registro["ubicacion"] or ""
                    )

                    stock_edit = st.number_input(
                        "Stock actual",
                        min_value=0.0,
                        value=float(registro["stock_actual"]),
                        disabled=True
                    )

                    st.caption(
                        "Para modificar las existencias, utiliza la pestaña Movimientos."
                    )

                    minimo_edit = st.number_input(
                        "Stock mínimo",
                        min_value=0.0,
                        value=float(registro["stock_minimo"])
                    )

                    precio_edit = st.number_input(
                        "Precio unitario (€)",
                        min_value=0.0,
                        value=float(registro["precio_unitario"])
                    )

                guardar_cambios = st.form_submit_button(
                    "Guardar cambios",
                    use_container_width=True
                )

                if guardar_cambios:

                    if not referencia_edit.strip() or not producto_edit.strip():
                        st.error(
                            "Referencia y producto son obligatorios."
                        )

                    else:
                        try:
                            actualizar_producto(
                                id_producto,
                                referencia_edit.strip().upper(),
                                producto_edit.strip(),
                                categoria_edit,
                                opciones_proveedores[proveedor_edit],
                                ubicacion_edit.strip(),
                                stock_edit,
                                minimo_edit,
                                precio_edit
                            )

                            st.success(
                                "Producto actualizado correctamente."
                            )
                            st.rerun()

                        except sqlite3.IntegrityError:
                            st.error("La referencia ya existe.")

            st.divider()

            st.subheader("Eliminar producto")

            st.warning(
                "La eliminación del producto es permanente."
            )

            confirmar = st.checkbox(
                "Confirmo que quiero eliminar este producto.",
                key=f"confirmar_producto_{id_producto}"
            )

          
            if st.button(
                "Eliminar producto",
                disabled=not confirmar,
                use_container_width=True,
                key=f"eliminar_producto_{id_producto}"
            ):

                try:
                    eliminar_producto(id_producto)
                    st.success("Producto eliminado correctamente.")
                    st.rerun()

                except ValueError as error:
                    st.error(str(error))



    with pestaña4:

        st.subheader("Registrar movimiento de almacén")
        st.caption("Control de entradas y salidas de materiales.")

        if inventario.empty:
            st.info("Primero debes registrar un producto.")

        else:

            opciones_movimiento = {
                f"{fila['referencia']} · {fila['producto']}":
                int(fila["id"])
                for _, fila in inventario.iterrows()
            }

            seleccion_movimiento = st.selectbox(
                "Seleccionar producto",
                list(opciones_movimiento.keys()),
                key="producto_movimiento"
            )

            id_movimiento = opciones_movimiento[
                seleccion_movimiento
            ]

            producto_movimiento = inventario[
                inventario["id"] == id_movimiento
            ].iloc[0]

            stock_disponible = float(
                producto_movimiento["stock_actual"]
            )

            st.metric(
                "Existencias actuales",
                f"{stock_disponible:g} unidades"
            )

            st.divider()

            tipo_movimiento = st.radio(
                "Tipo de movimiento",
                ["Entrada", "Salida"],
                horizontal=True
            )

            cantidad_movimiento = st.number_input(
                "Cantidad",
                min_value=0.01,
                value=1.0,
                step=1.0
            )

            if tipo_movimiento == "Entrada":

                motivos = [
                    "Recepción de pedido",
                    "Compra de material",
                    "Devolución",
                    "Ajuste de inventario",
                    "Otros"
                ]

                stock_previsto = (
                    stock_disponible + cantidad_movimiento
                )

            else:

                motivos = [
                    "Consumo en producción",
                    "Expedición de mercancía",
                    "Material defectuoso",
                    "Ajuste de inventario",
                    "Otros"
                ]

                stock_previsto = (
                    stock_disponible - cantidad_movimiento
                )

            motivo_movimiento = st.selectbox(
                "Motivo del movimiento",
                motivos
            )

            observaciones_movimiento = st.text_area(
                "Observaciones",
                key="observaciones_movimiento"
            )

            st.divider()

            col1, col2 = st.columns(2)

            with col1:
                st.metric(
                    "Stock anterior",
                    f"{stock_disponible:g}"
                )

            with col2:
                st.metric(
                    "Stock previsto",
                    f"{stock_previsto:g}"
                )

            if stock_previsto < 0:
                st.error("Stock insuficiente para esta salida.")

            if st.button(
                "Confirmar movimiento",
                type="primary",
                use_container_width=True,
                disabled=stock_previsto < 0
            ):

                try:

                    registrar_movimiento(
                        id_movimiento,
                        tipo_movimiento,
                        cantidad_movimiento,
                        motivo_movimiento,
                        observaciones_movimiento.strip()
                    )

                    st.success(
                        "Movimiento registrado correctamente."
                    )

                    st.rerun()

                except ValueError as error:
                    st.error(str(error))



    with pestaña5:

        st.subheader("Historial de movimientos")
        st.caption("Trazabilidad de entradas y salidas de almacén.")

        movimientos = obtener_movimientos()

        if movimientos.empty:
            st.info("Todavía no hay movimientos registrados.")

        else:

            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric(
                    "Total de movimientos",
                    len(movimientos)
                )

            with col2:
                st.metric(
                    "Unidades recibidas",
                    f"{movimientos.loc[movimientos['tipo'] == 'Entrada', 'cantidad'].sum():g}"
                )

            with col3:
                st.metric(
                    "Unidades retiradas",
                    f"{movimientos.loc[movimientos['tipo'] == 'Salida', 'cantidad'].sum():g}"
                )

            st.divider()

            col1, col2 = st.columns([2, 1])

            with col1:
                buscar_movimiento = st.text_input(
                    "Buscar por referencia o producto",
                    key="buscar_historial"
                )

            with col2:
                filtro_movimiento = st.selectbox(
                    "Tipo de movimiento",
                    ["Todos", "Entrada", "Salida"],
                    key="filtro_historial"
                )

            historial = movimientos.copy()

            if buscar_movimiento:

                historial = historial[
                    historial["referencia"].str.contains(
                        buscar_movimiento,
                        case=False,
                        regex=False
                    ) |
                    historial["producto"].str.contains(
                        buscar_movimiento,
                        case=False,
                        regex=False
                    )
                ]

            if filtro_movimiento != "Todos":

                historial = historial[
                    historial["tipo"] == filtro_movimiento
                ]

            historial["tipo"] = historial["tipo"].map({
                "Entrada": "🟢 Entrada",
                "Salida": "🔴 Salida"
            })

            st.caption(
                f"Movimientos encontrados: {len(historial)}"
            )

            st.dataframe(
                historial[[
                    "fecha",
                    "referencia",
                    "producto",
                    "tipo",
                    "cantidad",
                    "stock_anterior",
                    "stock_resultante",
                    "motivo",
                    "observaciones"
                ]],
                column_config={
                    "fecha": "Fecha",
                    "referencia": "Referencia",
                    "producto": "Producto",
                    "tipo": "Movimiento",
                    "cantidad": "Cantidad",
                    "stock_anterior": "Stock anterior",
                    "stock_resultante": "Stock final",
                    "motivo": "Motivo",
                    "observaciones": "Observaciones"
                },
                use_container_width=True,
                hide_index=True
            )

            st.download_button(
                "Descargar historial (CSV)",
                data=historial.to_csv(
                    index=False,
                    sep=";",
                    decimal=","
                ).encode("utf-8-sig"),
                file_name="BOIX_historial_movimientos.csv",
                mime="text/csv",
                use_container_width=True
            )


# ----------------------------------
# FACTURACIÓN
# ----------------------------------

elif seccion == "Facturación":

    st.caption("BOIX ERP · GESTIÓN FINANCIERA")
    st.title("Gestión de facturación")
    st.write("Registro de facturas de proveedores y control de pagos.")

    facturas = obtener_facturas()

    if not facturas.empty:

        facturas.loc[
            (facturas["estado"] == "Pendiente") &
            (facturas["fecha_vencimiento"] < str(date.today())),
            "estado"
        ] = "Vencida"

    total = facturas["importe_total"].sum()

    pagado = facturas.loc[
        facturas["estado"] == "Pagada",
        "importe_total"
    ].sum()

    pendiente = total - pagado

    vencidas = len(
        facturas[facturas["estado"] == "Vencida"]
    )

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Total facturado", f"{total:,.2f} €")
    col2.metric("Pagado", f"{pagado:,.2f} €")
    col3.metric("Pendiente de pago", f"{pendiente:,.2f} €")
    col4.metric("Facturas vencidas", vencidas)

    st.divider()

    pestaña1, pestaña2, pestaña3 = st.tabs([
        "Directorio de facturas",
        "Nueva factura",
        "Control de pagos"
    ])

    # DIRECTORIO

    with pestaña1:

        st.subheader("Directorio de facturas")

        col1, col2 = st.columns([2, 1])

        with col1:
            busqueda = st.text_input(
                "Buscar factura",
                placeholder="Referencia o proveedor..."
            )

        with col2:
            filtro = st.selectbox(
                "Estado",
                ["Todos", "Pendiente", "Pagada", "Vencida"]
            )

        datos = facturas.copy()

        if busqueda:
            datos = datos[
                datos["referencia"].str.contains(
                    busqueda, case=False, regex=False
                ) |
                datos["proveedor"].str.contains(
                    busqueda, case=False, regex=False
                ) |
                datos["numero_proveedor"].str.contains(
                    busqueda, case=False, regex=False
                )
            ]

        if filtro != "Todos":
            datos = datos[datos["estado"] == filtro]

        if datos.empty:
            st.info("No hay facturas para mostrar.")

        else:

            st.caption(f"Facturas encontradas: {len(datos)}")

            st.dataframe(
                datos[[
                    "referencia",
                    "numero_proveedor",
                    "pedido",
                    "proveedor",
                    "fecha_emision",
                    "fecha_vencimiento",
                    "base_imponible",
                    "iva",
                    "importe_total",
                    "estado"
                ]],
                column_config={
                    "referencia": "Referencia",
                    "numero_proveedor": "N.º factura proveedor",
                    "pedido": "Pedido",
                    "proveedor": "Proveedor",
                    "fecha_emision": "Emisión",
                    "fecha_vencimiento": "Vencimiento",
                    "base_imponible": st.column_config.NumberColumn(
                        "Base imponible", format="%.2f €"
                    ),
                    "iva": st.column_config.NumberColumn(
                        "IVA", format="%.0f %%"
                    ),
                    "importe_total": st.column_config.NumberColumn(
                        "Total", format="%.2f €"
                    ),
                    "estado": "Estado"
                },
                hide_index=True,
                use_container_width=True
            )

            st.download_button(
                "Descargar facturas (CSV)",
                data=datos.to_csv(
                    index=False,
                    sep=";",
                    decimal=","
                ).encode("utf-8-sig"),
                file_name="BOIX_facturas.csv",
                mime="text/csv"
            )

    # NUEVA FACTURA

    with pestaña2:

        st.subheader("Registrar factura de proveedor")

        pedidos_disponibles = obtener_pedidos_sin_factura()

        if pedidos_disponibles.empty:

            st.info("No hay pedidos disponibles para facturar.")

        else:

            opciones = {
                f"{fila['referencia']} · {fila['proveedor']}":
                int(fila["id"])
                for _, fila in pedidos_disponibles.iterrows()
            }

            seleccion = st.selectbox(
                "Seleccionar pedido",
                list(opciones.keys())
            )

            id_pedido = opciones[seleccion]

            pedido = pedidos_disponibles[
                pedidos_disponibles["id"] == id_pedido
            ].iloc[0]

            st.write(f"**Proveedor:** {pedido['proveedor']}")

            numero = st.text_input(
                "Número de factura del proveedor *"
            )

            col1, col2 = st.columns(2)

            with col1:
                fecha_emision = st.date_input(
                    "Fecha de emisión",
                    value=date.today()
                )

            with col2:
                fecha_vencimiento = st.date_input(
                    "Fecha de vencimiento",
                    value=date.today()
                )

            iva = st.selectbox(
                "Tipo de IVA (%)",
                [0, 4, 10, 21],
                index=3
            )

            observaciones = st.text_area("Observaciones")

            base = round(float(pedido["base_imponible"]), 2)
            cuota = round(base * iva / 100, 2)
            total_factura = round(base + cuota, 2)

            st.divider()

            col1, col2, col3 = st.columns(3)

            col1.metric("Base imponible", f"{base:,.2f} €")
            col2.metric("Cuota IVA", f"{cuota:,.2f} €")
            col3.metric("Total factura", f"{total_factura:,.2f} €")

            if st.button(
                "Registrar factura",
                type="primary",
                use_container_width=True
            ):

                try:

                    referencia = guardar_factura(
                        id_pedido,
                        numero,
                        fecha_emision,
                        fecha_vencimiento,
                        iva,
                        observaciones
                    )

                    st.session_state["aviso_factura"] = (
                        f"Factura {referencia} registrada correctamente."
                    )

                    st.rerun()

                except ValueError as error:

                    st.error(str(error))

    # CONTROL DE PAGOS

    with pestaña3:

        st.subheader("Seguimiento y control de pagos")

        if facturas.empty:

            st.info("Todavía no hay facturas registradas.")

        else:

            opciones = {
                f"{fila['referencia']} · {fila['proveedor']}":
                int(fila["id"])
                for _, fila in facturas.iterrows()
            }

            seleccion = st.selectbox(
                "Seleccionar factura",
                list(opciones.keys()),
                key="selector_pago_factura"
            )

            id_factura = opciones[seleccion]

            factura = facturas[
                facturas["id"] == id_factura
            ].iloc[0]
            st.download_button(
                label="📄 Descargar factura en PDF",
                data=generar_pdf_factura(factura),
                file_name=f"{factura['referencia']}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
            col1, col2, col3 = st.columns(3)

            col1.metric(
                "Importe",
                f"{factura['importe_total']:,.2f} €"
            )

            col2.metric("Estado actual", factura["estado"])

            col3.metric(
                "Vencimiento",
                factura["fecha_vencimiento"]
            )

            st.write(
                f"**Fecha de pago:** "
                f"{factura['fecha_pago'] or 'Sin registrar'}"
            )

            if factura["estado"] != "Pagada":

                if st.button(
                    "Marcar como pagada",
                    type="primary",
                    use_container_width=True
                ):

                    actualizar_estado_factura(
                        id_factura, "Pagada"
                    )

                    st.rerun()

            else:

                confirmar = st.checkbox(
                    "Confirmar que quiero revertir el pago"
                )

                if st.button(
                    "Marcar como pendiente",
                    disabled=not confirmar,
                    use_container_width=True
                ):

                    actualizar_estado_factura(
                        id_factura, "Pendiente"
                    )

                    st.rerun()

    if "aviso_factura" in st.session_state:

        st.success(
            st.session_state.pop("aviso_factura")
        )

    st.divider()
    st.caption("BOIX ERP · Gestión financiera")

elif seccion == "Incidencias":

    
    st.write(
        "Registro y seguimiento de incidencias "
        "relacionadas con pedidos, proveedores y materiales."
    )
    pestaña1, pestaña2, pestaña3 = st.tabs([
        "Registrar incidencia",
        "Directorio de incidencias",
        "Editar incidencia"
    ])

    st.download_button(
        label="📄 Descargar informe de incidencias (PDF)",
        data=generar_pdf_incidencias(),
        file_name=f"BOIX_Incidencias_{date.today()}.pdf",
        mime="application/pdf",
        use_container_width=True
    )


    with pestaña1:

        st.subheader("Nueva incidencia")

        proveedores = obtener_proveedores()
        pedidos = obtener_pedidos()

        opciones_proveedores = {"Sin proveedor": None}

        for _, fila in proveedores.iterrows():
            opciones_proveedores[
                f"{fila['empresa']} (ID {fila['id']})"
            ] = int(fila["id"])

        opciones_pedidos = {"Sin pedido": None}

        for _, fila in pedidos.iterrows():
            opciones_pedidos[
                str(fila["referencia"])
            ] = int(fila["id"])

        with st.form("formulario_incidencia"):

            titulo = st.text_input(
                "Título de la incidencia"
            )

            descripcion = st.text_area(
                "Descripción del problema"
            )

            tipo = st.selectbox(
                "Tipo de incidencia",
                [
                    "Material defectuoso",
                    "Retraso de entrega",
                    "Error en pedido",
                    "Problema con proveedor",
                    "Incidencia administrativa",
                    "Otra"
                ]
            )

            prioridad = st.selectbox(
                "Prioridad",
                ["Baja", "Media", "Alta", "Crítica"]
            )

            proveedor_seleccionado = st.selectbox(
                "Proveedor relacionado",
                list(opciones_proveedores.keys())
            )

            pedido_seleccionado = st.selectbox(
                "Pedido relacionado",
                list(opciones_pedidos.keys())
            )

            responsable = st.text_input(
                "Responsable del seguimiento"
            )

            observaciones = st.text_area(
                "Observaciones adicionales"
            )

            guardar = st.form_submit_button(
                "Registrar incidencia",
                use_container_width=True
            )

        if guardar:

            if not titulo.strip() or not descripcion.strip():

                st.error(
                    "Debes completar el título y la descripción."
                )

            else:

                try:
                    referencia = guardar_incidencia(
                        titulo.strip(),
                        descripcion.strip(),
                        tipo,
                        prioridad,
                        opciones_proveedores[
                            proveedor_seleccionado
                        ],
                        opciones_pedidos[
                            pedido_seleccionado
                        ],
                        responsable.strip(),
                        observaciones.strip()
                    )

                    st.success(
                        f"Incidencia {referencia} registrada correctamente."
                    )

                except Exception as error:

                    st.error(
                        f"No se pudo registrar la incidencia: {error}"
                    )

    with pestaña2:

        st.subheader("Directorio de incidencias")

        incidencias = obtener_incidencias()

        if incidencias.empty:

            st.info("Todavía no hay incidencias registradas.")

        else:

            st.divider()
            st.subheader("Seguimiento de incidencias")

            opciones = {
                f"{fila['referencia']} · {fila['titulo']}":
                int(fila["id"])
                for _, fila in incidencias.iterrows()
            }

            seleccion = st.selectbox(
                "Seleccionar incidencia",
                list(opciones.keys())
            )

            id_incidencia = opciones[seleccion]

            incidencia = incidencias[
                incidencias["id"] == id_incidencia
            ].iloc[0]

            st.info(
                f"Estado actual: {incidencia['estado']}"
            )

            with st.form("formulario_seguimiento"):

                nuevo_estado = st.selectbox(
                    "Nuevo estado",
                    ["Abierta", "En proceso", "Resuelta"],
                    index=[
                        "Abierta", "En proceso", "Resuelta"
                    ].index(incidencia["estado"])
                )

                solucion = st.text_area(
                    "Solución o acciones realizadas"
                )

                guardar_cambios = st.form_submit_button(
                    "Guardar seguimiento",
                    use_container_width=True
                )

            if guardar_cambios:

                if nuevo_estado == "Resuelta" and not solucion.strip():

                    st.error(
                        "Debes indicar una solución antes de resolver."
                    )

                else:

                    actualizar_incidencia(
                        id_incidencia,
                        nuevo_estado,
                        solucion.strip()
                    )

                    st.success(
                        "Seguimiento actualizado correctamente."
                    )

                    st.rerun()

            st.dataframe(
                incidencias,
                use_container_width=True,
                hide_index=True
            )

    with pestaña3:

        st.subheader("Editar incidencia existente")

        incidencias_editar = obtener_incidencias()

        if incidencias_editar.empty:
            st.info("No hay incidencias registradas.")

        else:
            opciones_editar = {
                f"{fila['referencia']} · {fila['titulo']}": int(fila["id"])
                for _, fila in incidencias_editar.iterrows()
            }

            incidencia_seleccionada = st.selectbox(
                "Selecciona la incidencia que deseas editar",
                list(opciones_editar.keys()),
                key="seleccionar_incidencia_editar"
            )

            id_editar = opciones_editar[incidencia_seleccionada]

            st.success(
                f"Incidencia seleccionada: {incidencia_seleccionada}"
            )

            datos = obtener_incidencia_por_id(id_editar)

            if datos is None:
                st.error("No se ha encontrado la incidencia.")
            else:
                titulo_actual, descripcion_actual, tipo_actual, \
                    prioridad_actual, responsable_actual, \
                    observaciones_actuales = datos

                tipos = [
                    "Material defectuoso",
                    "Retraso de entrega",
                    "Error en pedido",
                    "Problema con proveedor",
                    "Incidencia administrativa",
                    "Otra"
                ]

                prioridades = ["Baja", "Media", "Alta", "Crítica"]

                with st.form(
                    f"formulario_editar_incidencia_{id_editar}"
                ):

                    titulo_editado = st.text_input(
                        "Título",
                        value=titulo_actual
                    )

                    descripcion_editada = st.text_area(
                        "Descripción",
                        value=descripcion_actual
                    )

                    tipo_editado = st.selectbox(
                        "Tipo de incidencia",
                        tipos,
                        index=tipos.index(tipo_actual)
                        if tipo_actual in tipos else 0
                    )

                    prioridad_editada = st.selectbox(
                        "Prioridad",
                        prioridades,
                        index=prioridades.index(prioridad_actual)
                        if prioridad_actual in prioridades else 0
                    )

                    responsable_editado = st.text_input(
                        "Responsable",
                        value=responsable_actual or ""
                    )

                    observaciones_editadas = st.text_area(
                        "Observaciones",
                        value=observaciones_actuales or ""
                    )

                    guardar_edicion = st.form_submit_button(
                        "Guardar cambios",
                        use_container_width=True
                    )

                if guardar_edicion:

                    if not titulo_editado.strip() or not descripcion_editada.strip():
                        st.error(
                            "El título y la descripción son obligatorios."
                        )
                    else:
                        editar_incidencia(
                            id_editar,
                            titulo_editado.strip(),
                            descripcion_editada.strip(),
                            tipo_editado,
                            prioridad_editada,
                            responsable_editado.strip(),
                            observaciones_editadas.strip()
                        )

                        st.success(
                            "Incidencia actualizada correctamente."
                        )

                        st.rerun()
