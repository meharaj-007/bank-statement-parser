// Type definitions for Bank Statement Parser

export interface Statement {
  id: number;
  filename: string;
  upload_date: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  bank_name: string | null;
  account_number: string | null;
  period_start: string | null;
  period_end: string | null;
  transaction_count: number;
  page_count?: number;
}

export interface StatementDetail {
  id: number;
  filename: string;
  upload_date: string;
  status: string;
  page_count: number | null;
  customer_details: Record<string, any> | null;
  bank_details: Record<string, any> | null;
  transaction_count: number;
  error_message: string | null;
}

export interface TransactionSchema {
  columns: string[];
  column_metadata: Record<string, {
    type: 'date' | 'currency' | 'text' | 'number';
    display_name: string;
  }>;
  detected_bank_format: string | null;
}

export interface Transaction {
  id: number;
  transaction_date: string | null;
  amount: string | null;
  transaction_type: 'credit' | 'debit' | null;
  balance: string | null;
  data: Record<string, any>;  // Dynamic columns
  page_number: number | null;
}

export interface TransactionsResponse {
  transactions: Transaction[];
  pagination: {
    page: number;
    limit: number;
    total: number;
    pages: number;
  };
  summary: {
    total_credit: string;
    total_debit: string;
    net: string;
  };
}

export interface ProcessingStatus {
  statement_id: number;
  status: string;
  page_count: number | null;
  error_message: string | null;
  processing_started_at: string | null;
  processing_completed_at: string | null;
}

export interface PaginatedResponse<T> {
  [key: string]: T[] | any;
  pagination: {
    page: number;
    limit: number;
    total: number;
    pages: number;
  };
}

export interface UploadResponse {
  success: boolean;
  statement_id: number;
  message: string;
}

export interface StatementSummary {
  statement_id: number;
  total_transactions: number;
  total_credit: string;
  total_debit: string;
  net: string;
  credit_count: number;
  debit_count: number;
  opening_balance: string | null;
  closing_balance: string | null;
}
