import React, { useState } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

function SortableEmoji({ id, emoji, onClick }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging
  } = useSortable({ id });

  const [isHovered, setIsHovered] = useState(false);

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 999 : 'auto',
  };

  // Optimize: Use static image for palette to reduce lag, animate on hover
  const getEmojiUrl = (emoji) => {
      if (!emoji) return "";
      // If Discord emoji and animated
      if (emoji.source === 'discord' && emoji.animated && emoji.url.includes('.gif')) {
          if (!isHovered) {
             return emoji.url.replace('.gif', '.png');
          }
          return emoji.url;
      }
      // Local or static, return as is
      return emoji.url;
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={() => {
          if (!isDragging) onClick(emoji);
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className="w-12 h-12 p-1 m-1 bg-discord-dark hover:bg-gray-600 rounded cursor-pointer hover:cursor-pointer flex items-center justify-center border border-transparent hover:border-gray-500 transition-colors"
      title={emoji ? emoji.name : id}
    >
      {emoji ? (
        <img 
            src={getEmojiUrl(emoji)} 
            alt={emoji.name} 
            className="w-full h-full object-contain pointer-events-none" 
            loading="lazy"
        />
      ) : (
        <span className="text-xs text-gray-500 truncate">{id}</span>
      )}
    </div>
  );
}

export default React.memo(SortableEmoji);
