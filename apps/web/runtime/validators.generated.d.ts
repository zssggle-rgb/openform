import type { BridgeRequest, PROTOCOL } from "./bridge";

export function validRequest(value: unknown): value is BridgeRequest;
export function validHandshake(value: unknown): value is { protocolVersion: typeof PROTOCOL; phase: "init" | "ready" | "connect"; nonce: string };
export interface Receipt { receiptId: string; attemptId: string; revision: number; state: "saved" | "submitted"; receivedAt: string }
export function validReceipt(value: unknown): value is Receipt;
