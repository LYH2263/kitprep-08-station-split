export type Station = 'hot' | 'cold' | null

export interface DishRow {
  id: number
  code: string
  name: string
  portion_unit: string
  station: Station
}

export interface BookLine {
  ingredient_id: number
  ingredient_code: string
  ingredient_name: string
  unit: string
  qty: number
}

export interface Book {
  name: string
  lines: BookLine[]
}

export type BookKey = 'hot' | 'cold' | 'unassigned'

export interface PrepResult {
  id: number | null
  input_sig: string | null
  generated?: boolean
  order_id?: number
  order?: { id: number; code: string; outlet: string }
  books: Record<BookKey, Book>
  occupancy: BookLine[]
  prep_lines: Array<BookLine & { need_qty: number; stock_qty: number; shortage: number }>
  shortages: Array<BookLine & { need_qty: number; stock_qty: number; shortage: number }>
  stats: { ingredient_count: number; shortage_count: number; total_shortage_qty: number }
}

export interface InventoryRow {
  id: number
  code: string
  name: string
  unit: string
  stock_qty: number
  occupied_qty: number
  available_qty: number
}

export interface OrderRow {
  id: number
  code: string
  outlet: string
  status: string
}

export interface OrderLineRow {
  id: number
  dish_id: number
  dish_name: string
  portions: number
}
