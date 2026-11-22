<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  // Mail's icon names, drawn with Kern's icon set (Lucide), so mail looks like the rest of Kern.
  import {
    AlarmClock, Archive, ArrowLeft, Ban, Bell, BellOff, ChartColumn, Bold, Calendar, Check, ChevronDown, ChevronRight, Clock, Code,
    Copy, Download, Ellipsis, ExternalLink, Eye, File, Folder, FolderInput, Forward, Image, Inbox, Info, Italic,
    Keyboard, Link, List, ListOrdered, LogOut, Mail, MailOpen, MailX, Maximize2, Menu, Minimize2, Minus, Moon, Package,
    Columns2, PanelTop, Palette, Paperclip, Pencil, Pin, Play, Plus, Quote, RefreshCw, RemoveFormatting, Reply, ReplyAll, Rows3, Search, Send,
    Settings, Shield, ShieldAlert, Sparkles, SquareCheck, Star, StickyNote, Sun, Tag, Trash2, TriangleAlert, Truck,
    Underline, Undo2, X,
  } from '@lucide/svelte';

  let { name, size = 18, stroke = 1.75, fill = 'none', title = '' } = $props();

  const MAP = {
    inbox: Inbox, star: Star, send: Send, file: File, archive: Archive, trash: Trash2, spam: TriangleAlert,
    folder: Folder, label: Tag, all: Rows3, search: Search, pencil: Pencil, reply: Reply, replyAll: ReplyAll,
    forward: Forward, back: ArrowLeft, close: X, more: Ellipsis, menu: Menu, clip: Paperclip, check: Check,
    note: StickyNote, task: SquareCheck, shield: Shield, shieldAlert: ShieldAlert, block: Ban, settings: Settings,
    image: Image, mailOpen: MailOpen, mail: Mail, move: FolderInput, plus: Plus, minus: Minus, expand: Maximize2,
    minimize: Minimize2, download: Download, code: Code, bold: Bold, italic: Italic, underline: Underline, link: Link,
    list: List, olist: ListOrdered, quote: Quote, clearFormat: RemoveFormatting, sun: Sun, moon: Moon, logout: LogOut,
    keyboard: Keyboard, calendar: Calendar, pin: Pin, info: Info, eye: Eye, refresh: RefreshCw,
    chevronDown: ChevronDown, chevronRight: ChevronRight, package: Package, truck: Truck, copy: Copy,
    external: ExternalLink, mute: BellOff, bell: Bell, prompt: Sparkles, undo: Undo2, palette: Palette, clock: Clock,
    alarm: AlarmClock, unsubscribe: MailX, play: Play, split: Columns2, full: PanelTop, stats: ChartColumn,
  };
  const C = $derived(MAP[name] || Info);
</script>

<C size={size} strokeWidth={stroke} fill={fill} aria-hidden={title ? undefined : 'true'} aria-label={title || undefined}
   role={title ? 'img' : undefined} />
